"""NATS consumers for proposed orders and broker fills."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import nats
import structlog

from oms.state import OrderManager

log = structlog.get_logger()

PROPOSED_SUBJECT = "orders.proposed.>"
APPROVED_SUBJECT_PREFIX = "orders.approved."
FILLS_SUBJECT = "broker.fills.>"


class OmsEventConsumer:
    """Subscribe to order lifecycle and fill events."""

    def __init__(self, nats_url: str, manager: OrderManager) -> None:
        self._nats_url = nats_url
        self._manager = manager
        self._nc: nats.NATS | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        """Connect and bind subscriptions."""
        self._nc = await nats.connect(self._nats_url)
        await self._nc.subscribe(PROPOSED_SUBJECT, cb=self._on_proposed)
        await self._nc.subscribe(FILLS_SUBJECT, cb=self._on_fill)
        log.info(
            "oms_nats_consumer_started",
            proposed=PROPOSED_SUBJECT,
            fills=FILLS_SUBJECT,
        )

    async def stop(self) -> None:
        """Drain in-flight handlers and close NATS."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None
        log.info("oms_nats_consumer_stopped")

    async def publish_approved(self, order_id: str, payload: dict[str, Any]) -> None:
        """Publish ``orders.approved.{order_id}`` for the broker adapter."""
        if self._nc is None:
            msg = "NATS consumer not started"
            raise RuntimeError(msg)
        subject = f"{APPROVED_SUBJECT_PREFIX}{order_id}"
        await self._nc.publish(subject, json.dumps(payload).encode())
        log.info("order_approved_published", subject=subject)

    async def _on_proposed(self, msg: nats.aio.msg.Msg) -> None:
        task = asyncio.create_task(self._handle_proposed(msg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _on_fill(self, msg: nats.aio.msg.Msg) -> None:
        task = asyncio.create_task(self._handle_fill(msg))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_proposed(self, msg: nats.aio.msg.Msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            order_id = str(payload["order_id"])
            await self._manager.register_proposed(order_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_proposed_event_failed", error=str(exc))

    async def _handle_fill(self, msg: nats.aio.msg.Msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            order_id = str(payload["order_id"])
            await self._manager.handle_fill(
                order_id,
                qty=float(payload["qty"]),
                price=float(payload["price"]),
                commission=float(payload.get("commission", 0.0)),
                raw=payload,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_fill_event_failed", error=str(exc))
