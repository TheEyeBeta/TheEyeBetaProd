"""NATS subscriber for packaged snapshot events."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import nats
import structlog

from master_orchestrator.models import PackagedSnapshotEvent
from master_orchestrator.settings import Settings
from master_orchestrator.workflow import MarketTrioWorkflow

log = structlog.get_logger()

PACKAGED_SUBJECT = "snapshots.packaged.>"


class SnapshotEventConsumer:
    """Subscribe to packaged snapshots and launch market-trio workflows."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._nc: nats.NATS | None = None
        self._workflow = MarketTrioWorkflow(settings)
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def inflight_tasks(self) -> int:
        """Number of currently running async workflow tasks."""
        return len(self._tasks)

    async def start(self) -> None:
        """Connect to NATS and bind the subscription."""
        self._nc = await nats.connect(self._settings.nats_url)
        await self._nc.subscribe(PACKAGED_SUBJECT, cb=self._on_message)
        log.info("mo_snapshot_consumer_started", subject=PACKAGED_SUBJECT)

    async def stop(self) -> None:
        """Drain in-flight workflows and close NATS."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None
        log.info("mo_snapshot_consumer_stopped")

    async def _on_message(self, msg: nats.aio.msg.Msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            event = PackagedSnapshotEvent.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("mo_snapshot_event_invalid", error=str(exc))
            return

        task = asyncio.create_task(self._run_workflow(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_workflow(self, event: PackagedSnapshotEvent) -> None:
        try:
            result = await self._workflow.run(
                event.market,
                event.snapshot_id,
                trade_date=event.date,
            )
            if result.skipped:
                log.info(
                    "mo_workflow_skipped_duplicate",
                    market=event.market,
                    date=event.date,
                )
                return
            log.info(
                "mo_workflow_finished",
                market=event.market,
                snapshot_id=event.snapshot_id,
                order_id=result.order_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "mo_workflow_failed",
                market=event.market,
                snapshot_id=event.snapshot_id,
                error=str(exc),
            )
