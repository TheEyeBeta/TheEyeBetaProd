"""NATS JetStream consumer for ``data.snapshots.>`` events."""

from __future__ import annotations

import contextlib
import json
import os
from datetime import date
from typing import Any

import asyncpg
import nats
import structlog
from nats.js.api import ConsumerConfig, RetentionPolicy, StreamConfig

from snapshot_packager.idempotency import PackagingLock
from snapshot_packager.package import package_snapshot

log = structlog.get_logger()

STREAM_NAME = "DATA_SNAPSHOTS"
CONSUMER_NAME = "snapshot-packager"
FILTER_SUBJECT = "data.snapshots.>"


def database_url() -> str:
    """Return asyncpg-compatible DSN from ``INGEST_DATABASE_URL``."""
    raw = os.environ.get("INGEST_DATABASE_URL", "")
    if not raw:
        msg = "INGEST_DATABASE_URL is not set"
        raise OSError(msg)
    return (
        raw.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
    )


class SnapshotPackagerService:
    """Durable NATS consumer that builds and publishes packaged snapshots."""

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._nc: nats.NATS | None = None
        self._pool = pool
        self._owns_pool = pool is None
        self._lock = PackagingLock()
        self._pull_sub: Any = None

    @property
    def pool(self) -> asyncpg.Pool | None:
        """Expose the shared asyncpg pool."""
        return self._pool

    async def start(self) -> None:
        """Connect to NATS/Postgres and bind the durable pull consumer."""
        nats_url = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
        self._nc = await nats.connect(nats_url)
        js = self._nc.jetstream()

        with contextlib.suppress(Exception):
            await js.add_stream(
                config=StreamConfig(
                    name=STREAM_NAME,
                    subjects=[FILTER_SUBJECT],
                    retention=RetentionPolicy.LIMITS,
                ),
            )

        if self._pool is None:
            self._pool = await asyncpg.create_pool(database_url(), min_size=1, max_size=10)
            self._owns_pool = True

        self._pull_sub = await js.pull_subscribe(
            subject=FILTER_SUBJECT,
            durable=CONSUMER_NAME,
            stream=STREAM_NAME,
            config=ConsumerConfig(filter_subject=FILTER_SUBJECT),
        )
        log.info("snapshot_packager_consumer_started", stream=STREAM_NAME, consumer=CONSUMER_NAME)

    async def stop(self) -> None:
        """Drain connections."""
        self._pull_sub = None
        if self._owns_pool and self._pool is not None:
            await self._pool.close()
            self._pool = None
        if self._nc is not None:
            await self._nc.close()
            self._nc = None
        await self._lock.close()
        log.info("snapshot_packager_consumer_stopped")

    async def run_forever(self) -> None:
        """Pull messages until cancelled."""
        if self._pull_sub is None or self._pool is None:
            msg = "consumer not started"
            raise RuntimeError(msg)
        while True:
            try:
                messages = await self._pull_sub.fetch(batch=1, timeout=5)
            except nats.errors.TimeoutError:
                continue
            for msg in messages:
                try:
                    await self._handle_message(msg)
                    await msg.ack()
                except Exception as exc:  # noqa: BLE001
                    log.error("snapshot_packager_message_failed", error=str(exc))
                    await msg.nak()

    async def _handle_message(self, msg: nats.aio.msg.Msg) -> None:
        payload = json.loads(msg.data.decode())
        market = str(payload["market"]).upper()
        trade_date = date.fromisoformat(str(payload["date"]))
        log.info("data_snapshot_event_received", market=market, trade_date=str(trade_date))

        if not await self._lock.try_acquire(market, trade_date):
            return

        try:
            assert self._pool is not None
            result = await package_snapshot(self._pool, market, trade_date)

            subject = f"snapshots.packaged.{market}.{trade_date.isoformat()}"
            packaged_payload = json.dumps(
                {
                    "market": market,
                    "date": trade_date.isoformat(),
                    "snapshot_id": str(result.snapshot_id),
                    "blob_uri": result.blob_uri,
                    "schema_version": 1,
                },
            ).encode()
            assert self._nc is not None
            js = self._nc.jetstream()
            await js.publish(subject, packaged_payload)
            await self._lock.mark_complete(market, trade_date, str(result.snapshot_id))
            log.info(
                "snapshots_packaged_published",
                subject=subject,
                snapshot_id=str(result.snapshot_id),
                blob_uri=result.blob_uri,
            )
        except Exception:
            await self._lock.release(market, trade_date)
            raise
