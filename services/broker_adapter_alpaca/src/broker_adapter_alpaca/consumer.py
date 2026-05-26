"""NATS consumer for approved orders."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import nats
import structlog

from broker_adapter_alpaca.adapter import AlpacaAdapter
from zinc_schemas.broker_base import SubmitOrderRequest

log = structlog.get_logger()

APPROVED_SUBJECT = "orders.approved.>"


class ApprovedOrderConsumer:
    """Submit approved orders to Alpaca; fills are streamed via WebSocket."""

    def __init__(
        self,
        nats_url: str,
        adapter: AlpacaAdapter,
        *,
        symbol_resolver: dict[int, str] | None = None,
    ) -> None:
        self._nats_url = nats_url
        self._adapter = adapter
        self._symbols = symbol_resolver or {}
        self._nc: nats.NATS | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        """Subscribe to approved orders."""
        self._nc = await nats.connect(self._nats_url)
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
            symbol = self._symbols.get(instrument_id) or str(payload.get("symbol") or "AAPL")
            request = SubmitOrderRequest(
                order_id=order_id,
                symbol=symbol,
                side=str(payload["side"]),
                qty=float(payload["qty"]),
                order_type="market",
            )
            result = await asyncio.to_thread(self._adapter.submit_order, request)
            log.info(
                "broker_adapter_order_submitted",
                order_id=order_id,
                client_order_id=result.client_order_id,
                broker_order_id=result.broker_order_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("broker_adapter_approved_failed", error=str(exc))
