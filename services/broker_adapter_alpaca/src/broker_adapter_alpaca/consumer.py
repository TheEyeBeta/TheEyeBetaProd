"""NATS consumer for approved orders."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import nats
import psycopg
import structlog

from broker_adapter_alpaca.adapter import AlpacaAdapter
from broker_adapter_alpaca.live_gate import (
    DataGapBlockError,
    LiveTradingNotApprovedError,
    TradingDisabledError,
    assert_order_submission_allowed,
)
from broker_adapter_alpaca.settings import Settings
from zinc_schemas.broker_base import SubmitOrderRequest

log = structlog.get_logger()

APPROVED_SUBJECT = "orders.approved.>"


class ApprovedOrderConsumer:
    """Submit approved orders to Alpaca; fills are streamed via WebSocket."""

    def __init__(
        self,
        settings: Settings,
        adapter: AlpacaAdapter,
        *,
        symbol_resolver: dict[int, str] | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._symbols = symbol_resolver or {}
        self._nc: nats.NATS | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        """Subscribe to approved orders."""
        self._nc = await nats.connect(self._settings.nats_url)
        await self._nc.subscribe(APPROVED_SUBJECT, cb=self._on_approved)
        log.info("broker_adapter_consumer_started", subject=APPROVED_SUBJECT)

    async def stop(self) -> None:
        """Close NATS."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None

    async def _on_approved(self, msg: nats.aio.msg.Msg) -> None:
        task = asyncio.create_task(self._handle(msg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle(self, msg: nats.aio.msg.Msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            order_id = str(payload["order_id"])
            instrument_id = int(payload["instrument_id"])
            symbol = (
                self._symbols.get(instrument_id)
                or payload.get("symbol")
                or await self._resolve_symbol(instrument_id)
            )
            if not symbol:
                log.error(
                    "broker_adapter_missing_symbol",
                    order_id=order_id,
                    instrument_id=instrument_id,
                )
                return
            live_mode = self._settings.mode == "live"
            try:
                await assert_order_submission_allowed(
                    self._settings.pg_dsn(),
                    live_mode=live_mode,
                    redis_url=self._settings.redis_url or None,
                )
            except (DataGapBlockError, LiveTradingNotApprovedError, TradingDisabledError) as exc:
                log.error(
                    "broker_adapter_gate_blocked",
                    order_id=order_id,
                    error=str(exc),
                )
                return
            request = SubmitOrderRequest(
                order_id=order_id,
                symbol=str(symbol),
                side=str(payload["side"]),
                qty=float(payload["qty"]),
                order_type="market",
            )
            result = await asyncio.to_thread(self._adapter.submit_order, request)
            await self._persist_submission(
                result.order_id,
                result.client_order_id,
                result.broker_order_id,
            )
            log.info(
                "broker_adapter_order_submitted",
                order_id=order_id,
                client_order_id=result.client_order_id,
                broker_order_id=result.broker_order_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("broker_adapter_approved_failed", error=str(exc))

    async def _persist_submission(
        self,
        order_id: str,
        client_order_id: str,
        broker_order_id: str,
    ) -> None:
        """Persist broker identifiers once Alpaca accepts a submitted order."""
        async with await psycopg.AsyncConnection.connect(self._settings.pg_dsn()) as conn:
            await conn.execute(
                """
                UPDATE theeyebeta.orders
                   SET client_order_id = %s,
                       broker_order_id = %s,
                       updated_at = now()
                 WHERE id = %s
                """,
                (client_order_id, broker_order_id, order_id),
            )
            await conn.commit()

    async def _resolve_symbol(self, instrument_id: int) -> str | None:
        """Resolve ticker symbol from Postgres when the approved event only has an ID."""
        try:
            async with await psycopg.AsyncConnection.connect(self._settings.pg_dsn()) as conn:
                cur = await conn.execute(
                    "SELECT symbol FROM theeyebeta.instruments WHERE id = %s",
                    (instrument_id,),
                )
                row = await cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "broker_adapter_symbol_lookup_failed",
                instrument_id=instrument_id,
                error=str(exc),
            )
            return None
        return str(row[0]) if row else None
