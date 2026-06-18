"""Alpaca Markets implementation of :class:`~zinc_schemas.broker_base.BrokerAdapter`."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from uuid6 import uuid7

from broker_adapter_alpaca.settings import Settings
from zinc_schemas.broker_base import SubmitOrderRequest, SubmitOrderResult, TradeUpdateHandler

log = structlog.get_logger()

_WS_PING_INTERVAL = 10
_WS_PING_TIMEOUT = 180

_TERMINAL_EVENTS = frozenset({"fill", "canceled", "rejected", "expired"})


_KNOWN_ACCOUNTS = frozenset({"zinc", "nyse", "nasdaq"})


class AlpacaAdapter:
    """Broker adapter backed by alpaca-py ``TradingClient`` and ``TradingStream``.

    Three paper sub-accounts are supported:
      - ``zinc``   — ZINC INVESTMENTS fund account (default)
      - ``nyse``   — NYSE-universe individual stocks
      - ``nasdaq`` — NASDAQ-universe individual stocks

    Pass ``account="nyse"`` / ``account="nasdaq"`` on ``SubmitOrderRequest`` to
    route to the correct sub-account. Each sub-account uses its own API credentials
    and therefore its own ``TradingClient`` instance.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, Any] = {}  # account name → TradingClient
        self._stream: Any | None = None
        self._order_by_client: dict[str, str] = {}
        self._client_by_order: dict[str, str] = {}
        self._account_by_order: dict[str, str] = {}  # internal order_id → account name

    @property
    def mode(self) -> str:
        """Configured broker mode (paper or live)."""
        return self._settings.mode

    def register_order_mapping(self, order_id: str, client_order_id: str, account: str) -> None:
        """Map internal order id to Alpaca client_order_id and sub-account for routing."""
        self._order_by_client[client_order_id] = order_id
        self._client_by_order[order_id] = client_order_id
        self._account_by_order[order_id] = account

    def resolve_order_id(self, client_order_id: str) -> str | None:
        """Resolve internal order id from Alpaca client_order_id."""
        return self._order_by_client.get(client_order_id)

    async def resolve_order_id_durable(self, client_order_id: str) -> str | None:
        """Resolve internal order id, falling back to Postgres on a cache miss.

        ``_order_by_client`` is in-memory and lost on every restart; the OMS
        persists ``client_order_id`` on submission (see
        ``ApprovedOrderConsumer._persist_submission``), so a DB lookup recovers
        the mapping for trade updates that arrive after a restart.
        """
        cached = self._order_by_client.get(client_order_id)
        if cached is not None:
            return cached
        import psycopg  # noqa: PLC0415

        async with await psycopg.AsyncConnection.connect(self._settings.pg_dsn()) as conn:
            cur = await conn.execute(
                "SELECT id FROM theeyebeta.orders WHERE client_order_id = %s",
                (client_order_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        order_id = str(row[0])
        self._order_by_client[client_order_id] = order_id
        return order_id

    def _client(self, account: str = "zinc") -> object:
        if account not in _KNOWN_ACCOUNTS:
            msg = f"unknown account '{account}'; must be one of {sorted(_KNOWN_ACCOUNTS)}"
            raise ValueError(msg)
        if account not in self._clients:
            from alpaca.trading.client import TradingClient  # noqa: PLC0415

            self._clients[account] = TradingClient(
                self._settings.api_key_for_account(account),
                self._settings.api_secret_for_account(account),
                paper=self._settings.paper_trading_enabled(),
            )
        return self._clients[account]

    def _trading_stream(self) -> Any:  # noqa: ANN401 — Alpaca SDK stream type is not exported
        # Stream is pinned to the zinc (primary) account. Fill events from nyse/nasdaq
        # accounts require separate TradingStream instances; add when multi-stream is needed.
        if self._stream is None:
            from alpaca.trading.stream import TradingStream  # noqa: PLC0415

            self._stream = TradingStream(
                self._settings.api_key_for_account("zinc"),
                self._settings.api_secret_for_account("zinc"),
                paper=self._settings.paper_trading_enabled(),
                websocket_params={
                    "ping_interval": _WS_PING_INTERVAL,
                    "ping_timeout": _WS_PING_TIMEOUT,
                },
            )
        return self._stream

    def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit a market order to the sub-account named in ``request.account``."""
        from alpaca.trading.enums import OrderSide, TimeInForce  # noqa: PLC0415
        from alpaca.trading.requests import MarketOrderRequest  # noqa: PLC0415

        account = request.account or "zinc"
        client_order_id = str(uuid7())
        self.register_order_mapping(request.order_id, client_order_id, account)

        order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
        if request.order_type.lower() != "market":
            msg = f"unsupported order_type: {request.order_type}"
            raise ValueError(msg)

        placed = self._client(account).submit_order(
            MarketOrderRequest(
                symbol=request.symbol,
                qty=request.qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            ),
        )
        raw = _order_to_dict(placed)
        log.info(
            "alpaca_order_submitted",
            order_id=request.order_id,
            client_order_id=client_order_id,
            alpaca_id=raw["id"],
            account=account,
        )
        return SubmitOrderResult(
            order_id=request.order_id,
            broker_order_id=raw["id"],
            client_order_id=client_order_id,
            symbol=request.symbol,
            side=request.side.lower(),
            qty=float(request.qty),
            status=raw["status"],
            account=account,
            raw=raw,
        )

    def cancel_order(self, broker_order_id: str, *, order_id: str | None = None) -> dict[str, Any]:
        """Cancel an open order by Alpaca order id.

        Pass ``order_id`` (internal) so the correct sub-account client is used.
        Falls back to the zinc account when order_id is unknown.
        """
        from uuid import UUID  # noqa: PLC0415

        account = self._account_by_order.get(order_id or "", "zinc")
        canceled = self._client(account).cancel_order_by_id(UUID(broker_order_id))
        raw = _order_to_dict(canceled)
        log.info("alpaca_order_canceled", broker_order_id=broker_order_id, account=account)
        return raw

    def list_positions(self, account: str = "zinc") -> list[dict[str, Any]]:
        """Return open positions for the named sub-account."""
        positions = self._client(account).get_all_positions()
        return [
            {
                "symbol": str(p.symbol),
                "qty": float(p.qty),
                "market_value": float(p.market_value or 0),
                "avg_entry_price": float(p.avg_entry_price or 0),
                "account": account,
            }
            for p in positions
        ]

    def get_account(self, account: str = "zinc") -> dict[str, Any]:
        """Return cash/equity/buying_power for the named sub-account (read-only)."""
        acct = self._client(account).get_account()
        return {
            "account": account,
            "cash": float(acct.cash or 0),
            "equity": float(acct.equity or 0),
            "buying_power": float(acct.buying_power or 0),
            "portfolio_value": float(acct.portfolio_value or 0),
        }

    def list_all_accounts(self) -> list[dict[str, Any]]:
        """Return cash/equity/buying_power across all three sub-accounts."""
        return [self.get_account(acct) for acct in sorted(_KNOWN_ACCOUNTS)]

    def list_all_positions(self) -> list[dict[str, Any]]:
        """Return open positions across all three sub-accounts."""
        result: list[dict[str, Any]] = []
        for acct in sorted(_KNOWN_ACCOUNTS):
            result.extend(self.list_positions(acct))
        return result

    def list_orders(self, account: str = "zinc", *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent orders for the named sub-account."""
        from alpaca.trading.requests import GetOrdersRequest  # noqa: PLC0415

        orders = self._client(account).get_orders(
            filter=GetOrdersRequest(limit=limit, nested=True),
        )
        return [_order_to_dict(o) for o in orders]

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        """Fetch one order by client_order_id (e2e / diagnostics)."""
        from alpaca.trading.requests import GetOrdersRequest  # noqa: PLC0415

        order_id = self.resolve_order_id(client_order_id)
        account = self._account_by_order.get(order_id or "", "zinc")
        orders = self._client(account).get_orders(
            filter=GetOrdersRequest(client_order_ids=[client_order_id]),
        )
        if not orders:
            return None
        return _order_to_dict(orders[0])

    async def stream_trade_updates(self, handler: TradeUpdateHandler) -> None:
        """Run Alpaca ``TradingStream`` until :meth:`stop_stream` is called."""
        stream = self._trading_stream()

        async def _on_update(data: dict[str, Any]) -> None:
            normalized = await normalize_trade_update(data, self)
            await handler(normalized)

        stream.subscribe_trade_updates(_on_update)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, stream.run)

    def stop_stream(self) -> None:
        """Signal the trading WebSocket to stop."""
        if self._stream is not None:
            self._stream.stop()


def _order_to_dict(order: object) -> dict[str, Any]:
    """Serialize an Alpaca order model to a plain dict."""
    if hasattr(order, "model_dump"):
        payload = order.model_dump(mode="json")
    else:
        payload = json.loads(json.dumps(order, default=str))
    return {
        "id": str(payload.get("id") or ""),
        "client_order_id": str(payload.get("client_order_id") or ""),
        "symbol": str(payload.get("symbol") or ""),
        "side": str(payload.get("side") or "").lower(),
        "qty": float(payload.get("qty") or 0),
        "filled_qty": float(payload.get("filled_qty") or 0),
        "status": str(payload.get("status") or "").lower(),
        "filled_avg_price": float(payload.get("filled_avg_price") or 0),
    }


async def normalize_trade_update(
    data: dict[str, Any] | object,
    adapter: AlpacaAdapter,
) -> dict[str, Any]:
    """Map Alpaca trade_update payload to NATS fill envelope."""
    if not isinstance(data, dict):
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        else:
            data = json.loads(json.dumps(data, default=str))
    event = str(data.get("event") or data.get("type") or "unknown").lower()
    order_raw = data.get("order") or {}
    if isinstance(order_raw, dict):
        order = _order_to_dict(order_raw) if order_raw.get("id") else order_raw
    else:
        order = _order_to_dict(order_raw)
    client_order_id = str(order.get("client_order_id") or "")
    order_id = await adapter.resolve_order_id_durable(client_order_id) or ""

    fill_qty = float(order.get("filled_qty") or 0)
    price = float(order.get("filled_avg_price") or 0)

    return {
        "order_id": order_id,
        "client_order_id": client_order_id,
        "broker_order_id": str(order.get("id") or ""),
        "event": event,
        "symbol": str(order.get("symbol") or ""),
        "side": str(order.get("side") or "").lower(),
        "qty": fill_qty,
        "price": price,
        "commission": 0.0,
        "status": str(order.get("status") or "").lower(),
        "order": order,
        "raw": data,
        "terminal": event in _TERMINAL_EVENTS,
    }
