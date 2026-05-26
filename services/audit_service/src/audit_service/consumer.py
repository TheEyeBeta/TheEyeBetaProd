"""NATS JetStream durable consumer for ``audit.events.>``."""

from __future__ import annotations

import contextlib
import json
from typing import Any

import nats
import structlog
from nats.js.api import ConsumerConfig, RetentionPolicy, StreamConfig

from audit_service.chain import append_chained_row
from audit_service.models import AuditEventMessage
from audit_service.settings import Settings

log = structlog.get_logger()

FILTER_SUBJECT = "audit.events.>"


class AuditEventConsumer:
    """Pull-based durable subscriber that appends hash-chained audit rows."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._nc: nats.NATS | None = None
        self._pull_sub: Any = None

    async def start(self) -> None:
        """Connect to NATS and bind the durable JetStream consumer."""
        self._nc = await nats.connect(self._settings.nats_url)
        js = self._nc.jetstream()
        stream = self._settings.jetstream_stream
        durable = self._settings.jetstream_durable

        with contextlib.suppress(Exception):
            await js.add_stream(
                config=StreamConfig(
                    name=stream,
                    subjects=[FILTER_SUBJECT],
                    retention=RetentionPolicy.LIMITS,
                ),
            )

        self._pull_sub = await js.pull_subscribe(
            subject=FILTER_SUBJECT,
            durable=durable,
            stream=stream,
            config=ConsumerConfig(filter_subject=FILTER_SUBJECT),
        )
        log.info(
            "audit_nats_consumer_started",
            stream=stream,
            durable=durable,
            subject=FILTER_SUBJECT,
        )

    async def stop(self) -> None:
        """Close the NATS connection."""
        self._pull_sub = None
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
        log.info("audit_nats_consumer_stopped")

    async def run_forever(self) -> None:
        """Pull messages until cancelled."""
        if self._pull_sub is None:
            msg = "audit consumer not started"
            raise RuntimeError(msg)
        dsn = self._settings.pg_dsn()
        while True:
            try:
                messages = await self._pull_sub.fetch(batch=1, timeout=5)
            except nats.errors.TimeoutError:
                continue
            for msg in messages:
                try:
                    await self._handle_message(dsn, msg)
                    await msg.ack()
                except Exception as exc:  # noqa: BLE001
                    log.error("audit_event_failed", error=str(exc), subject=msg.subject)
                    await msg.nak()

    async def _handle_message(self, dsn: str, msg: nats.aio.msg.Msg) -> None:
        raw = json.loads(msg.data.decode())
        event = AuditEventMessage.model_validate(raw)
        await append_chained_row(
            dsn,
            actor=event.actor,
            action=event.action,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
            ts=event.ts,
        )
        log.info(
            "audit_event_appended",
            subject=msg.subject,
            action=event.action,
            entity_type=event.entity_type,
        )
