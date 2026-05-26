"""Alpaca TradingStream → NATS ``broker.fills.{order_id}`` publisher."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import nats
import structlog

from broker_adapter_alpaca.adapter import AlpacaAdapter

log = structlog.get_logger()

FILLS_SUBJECT_PREFIX = "broker.fills."
_PUBLISH_EVENTS = frozenset(
    {"new", "partial_fill", "fill", "canceled", "rejected", "cancelled"},
)


class TradeUpdateStreamer:
    """Subscribe to Alpaca trade updates and publish fills on NATS."""

    def __init__(self, adapter: AlpacaAdapter, nats_url: str) -> None:
        self._adapter = adapter
        self._nats_url = nats_url
        self._nc: nats.NATS | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Connect NATS and start the WebSocket stream in the background."""
        self._nc = await nats.connect(self._nats_url)
        self._task = asyncio.create_task(self._run(), name="alpaca-trade-stream")
        log.info("trade_update_streamer_started")

    async def stop(self) -> None:
        """Stop WebSocket and drain NATS."""
        self._adapter.stop_stream()
        if self._task is not None:
            self._task.cancel()
            with asyncio.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None
        log.info("trade_update_streamer_stopped")

    async def _run(self) -> None:
        try:
            await self._adapter.stream_trade_updates(self._on_trade_update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("trade_update_stream_failed", error=str(exc))

    async def _on_trade_update(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event") or "").lower()
        if event_type not in _PUBLISH_EVENTS:
            return

        order_id = str(event.get("order_id") or "")
        if not order_id:
            log.warning(
                "trade_update_missing_order_id",
                client_order_id=event.get("client_order_id"),
                event=event_type,
            )
            return

        if self._nc is None:
            return

        subject = f"{FILLS_SUBJECT_PREFIX}{order_id}"
        await self._nc.publish(subject, json.dumps(event).encode())
        log.info(
            "broker_fill_published",
            subject=subject,
            trade_event=event_type,
            status=event.get("status"),
        )
