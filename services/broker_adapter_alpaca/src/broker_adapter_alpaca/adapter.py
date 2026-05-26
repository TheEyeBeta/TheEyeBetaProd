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


class AlpacaAdapter:
    """Broker adapter backed by alpaca-py ``TradingClient`` and ``TradingStream``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._trading: Any | None = None
        self._stream: Any | None = None
        self._order_by_client: dict[str, str] = {}
        self._client_by_order: dict[str, str] = {}

    @property
    def mode(self) -> str:
        """Configured broker mode (paper or live)."""
        return self._settings.mode

    def register_order_mapping(self, order_id: str, client_order_id: str) -> None:
        """Map internal order id to Alpaca client_order_id for fill routing."""
        self._order_by_client[client_order_id] = order_id
        self._client_by_order[order_id] = client_order_id

    def resolve_order_id(self, client_order_id: str) -> str | None:
        """Resolve internal order id from Alpaca client_order_id."""
        return self._order_by_client.get(client_order_id)

    def _client(self) -> object:
        if self._trading is None:
            from alpaca.trading.client import TradingClient  # noqa: PLC0415

            self._trading = TradingClient(
                self._settings.api_key(),
                self._settings.api_secret(),
                paper=self._settings.paper_trading_enabled(),
            )
        return self._trading

    def _trading_stream(self) -> Any:
        if self._stream is None:
            from alpaca.trading.stream import TradingStream  # noqa: PLC0415

            self._stream = TradingStream(
                self._settings.api_key(),
                self._settings.api_secret(),
                paper=self._settings.paper_trading_enabled(),
                websocket_params={
                    "ping_interval": _WS_PING_INTERVAL,
                    "ping_timeout": _WS_PING_TIMEOUT,
                },
            )
        return self._stream

    def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit a market order with a UUIDv7 ``client_order_id``."""
        from alpaca.trading.enums import OrderSide, TimeInForce  # noqa: PLC0415
        from alpaca.trading.requests import MarketOrderRequest  # noqa: PLC0415

        client_order_id = str(uuid7())
        self.register_order_mapping(request.order_id, client_order_id)

        order_side = OrderSide.BUY if request.side.lower() == "buy" else OrderSide.SELL
        if request.order_type.lower() != "market":
            msg = f"unsupported order_type: {request.order_type}"
            raise ValueError(msg)

        placed = self._client().submit_order(
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
        )
        return SubmitOrderResult(
            order_id=request.order_id,
            broker_order_id=raw["id"],
            client_order_id=client_order_id,
            symbol=request.symbol,
            side=request.side.lower(),
            qty=float(request.qty),
            status=raw["status"],
            raw=raw,
        )

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        """Cancel an open order by Alpaca order id."""
        from uuid import UUID  # noqa: PLC0415

        canceled = self._client().cancel_order_by_id(UUID(broker_order_id))
        raw = _order_to_dict(canceled)
        log.info("alpaca_order_canceled", broker_order_id=broker_order_id)
        return raw

    def list_positions(self) -> list[dict[str, Any]]:
        """Return open positions normalized to symbol/qty."""
        positions = self._client().get_all_positions()
        return [
            {
                "symbol": str(p.symbol),
                "qty": float(p.qty),
                "market_value": float(p.market_value or 0),
                "avg_entry_price": float(p.avg_entry_price or 0),
            }
            for p in positions
        ]

    def list_orders(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent orders normalized for reconciliation."""
        from alpaca.trading.requests import GetOrdersRequest  # noqa: PLC0415

        orders = self._client().get_orders(
            filter=GetOrdersRequest(limit=limit, nested=True),
        )
        return [_order_to_dict(o) for o in orders]

    def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        """Fetch one order by client_order_id (e2e / diagnostics)."""
        from alpaca.trading.requests import GetOrdersRequest  # noqa: PLC0415

        orders = self._client().get_orders(
            filter=GetOrdersRequest(client_order_ids=[client_order_id]),
        )
        if not orders:
            return None
        return _order_to_dict(orders[0])

    async def stream_trade_updates(self, handler: TradeUpdateHandler) -> None:
        """Run Alpaca ``TradingStream`` until :meth:`stop_stream` is called."""
        stream = self._trading_stream()

        async def _on_update(data: dict[str, Any]) -> None:
            normalized = normalize_trade_update(data, self)
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


def normalize_trade_update(data: dict[str, Any], adapter: AlpacaAdapter) -> dict[str, Any]:
    """Map Alpaca trade_update payload to NATS fill envelope."""
    event = str(data.get("event") or data.get("type") or "unknown").lower()
    order_raw = data.get("order") or {}
    if isinstance(order_raw, dict):
        order = _order_to_dict(order_raw) if order_raw.get("id") else order_raw
    else:
        order = _order_to_dict(order_raw)
    client_order_id = str(order.get("client_order_id") or "")
    order_id = adapter.resolve_order_id(client_order_id) or ""

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
