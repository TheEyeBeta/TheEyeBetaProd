"""Nightly WORM checkpoint export with Ed25519 signing."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import psycopg
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from minio import Minio

from audit_service.chain import GENESIS_HASH, canonical_row_json, compute_row_hash
from audit_service.settings import Settings

log = structlog.get_logger()

AuditLogRow = tuple[int, datetime, str, str, str, str, dict[str, Any], bytes | None, bytes]


@dataclass(frozen=True)
class CheckpointRecord:
    """One signed audit checkpoint."""

    checkpoint_id: str
    last_row_id: int
    last_row_hash: bytes
    signature: bytes
    signing_ts: datetime
    count: int


def load_signing_key(raw: str) -> Ed25519PrivateKey:
    """Parse ``AUDIT_SIGNING_KEY`` as base64 or hex-encoded 32-byte seed."""
    text = raw.strip()
    if not text:
        msg = "AUDIT_SIGNING_KEY is not set"
        raise OSError(msg)
    try:
        key_bytes = base64.b64decode(text, validate=True)
    except Exception:
        key_bytes = bytes.fromhex(text)
    if len(key_bytes) != 32:
        msg = "AUDIT_SIGNING_KEY must decode to 32 bytes"
        raise ValueError(msg)
    return Ed25519PrivateKey.from_private_bytes(key_bytes)


async def ensure_audit_partitions(dsn: str, *, months_ahead: int = 6) -> None:
    """Create monthly ``audit_log`` partitions via the DB helper."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            "SELECT theeyebeta.ensure_audit_partitions(%s)",
            (months_ahead,),
        )
        await conn.commit()
    log.info("audit_partitions_ensured", months_ahead=months_ahead)


async def fetch_last_checkpoint(dsn: str) -> tuple[int, bytes] | None:
    """Return ``(last_row_id, last_row_hash)`` from the newest checkpoint."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT last_row_id, last_row_hash
              FROM theeyebeta.audit_checkpoints
             ORDER BY signing_ts DESC
             LIMIT 1
            """,
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return int(row[0]), bytes(row[1])


async def fetch_rows_after_id(dsn: str, after_id: int) -> list[AuditLogRow]:
    """Load rows with ``id > after_id`` ordered ascending."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT id, ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash
              FROM theeyebeta.audit_log
             WHERE id > %s
             ORDER BY id ASC
            """,
            (after_id,),
        )
        return await cur.fetchall()


async def compute_running_hash(
    dsn: str,
    *,
    start_after_id: int,
    initial_prev_hash: bytes,
) -> tuple[int, bytes, int]:
    """Walk the chain from ``start_after_id`` and return latest id/hash and row count."""
    rows = await fetch_rows_after_id(dsn, start_after_id)
    if not rows:
        if start_after_id == 0:
            return 0, GENESIS_HASH, 0
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            cur = await conn.execute(
                "SELECT id, row_hash FROM theeyebeta.audit_log WHERE id = %s",
                (start_after_id,),
            )
            anchor = await cur.fetchone()
        if anchor is None:
            return 0, initial_prev_hash, 0
        return int(anchor[0]), bytes(anchor[1]), 0

    expected_prev = initial_prev_hash
    last_id = start_after_id
    last_hash = initial_prev_hash
    for row in rows:
        row_id = int(row[0])
        payload = row[6] if isinstance(row[6], dict) else json.loads(row[6])
        prev_hash = bytes(row[7]) if row[7] is not None else GENESIS_HASH
        row_hash = bytes(row[8])
        if prev_hash != expected_prev:
            msg = f"chain break at row {row_id}: prev_hash mismatch"
            raise ValueError(msg)
        canonical = canonical_row_json(
            ts=row[1],
            actor=str(row[2]),
            action=str(row[3]),
            entity_type=str(row[4]),
            entity_id=str(row[5]),
            payload=payload,
        )
        recomputed = compute_row_hash(expected_prev, canonical)
        if row_hash != recomputed:
            msg = f"chain break at row {row_id}: row_hash mismatch"
            raise ValueError(msg)
        expected_prev = row_hash
        last_id = row_id
        last_hash = row_hash
    return last_id, last_hash, len(rows)


def checkpoint_to_json(record: CheckpointRecord) -> dict[str, Any]:
    """Serialize a checkpoint for WORM object storage."""
    return {
        "checkpoint_id": record.checkpoint_id,
        "last_row_id": record.last_row_id,
        "last_row_hash": base64.b64encode(record.last_row_hash).decode("ascii"),
        "signature": base64.b64encode(record.signature).decode("ascii"),
        "signing_ts": record.signing_ts.astimezone(UTC).isoformat(),
        "count": record.count,
    }


def upload_checkpoint_json(settings: Settings, *, object_key: str, body: dict[str, Any]) -> str:
    """Write checkpoint JSON to MinIO and return ``s3://`` URI."""
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_endpoint.startswith("https"),
    )
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    client.put_object(
        bucket,
        object_key,
        BytesIO(payload),
        length=len(payload),
        content_type="application/json",
    )
    uri = f"s3://{bucket}/{object_key}"
    log.info("audit_checkpoint_uploaded", uri=uri)
    return uri


async def insert_checkpoint_row(
    dsn: str,
    *,
    record: CheckpointRecord,
    s3_uri: str,
) -> None:
    """Persist checkpoint metadata in ``audit_checkpoints``."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_checkpoints (
                checkpoint_id, last_row_id, last_row_hash,
                signature, signing_ts, row_count, s3_uri
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.checkpoint_id,
                record.last_row_id,
                record.last_row_hash,
                record.signature,
                record.signing_ts,
                record.count,
                s3_uri,
            ),
        )
        await conn.commit()


async def run_nightly_export(settings: Settings) -> CheckpointRecord | None:
    """Execute partition maintenance, chain verification, sign, and upload."""
    dsn = settings.pg_dsn()
    await ensure_audit_partitions(dsn, months_ahead=6)

    anchor = await fetch_last_checkpoint(dsn)
    if anchor is None:
        start_after_id = 0
        initial_prev = GENESIS_HASH
    else:
        start_after_id, initial_prev = anchor

    last_row_id, last_row_hash, count = await compute_running_hash(
        dsn,
        start_after_id=start_after_id,
        initial_prev_hash=initial_prev,
    )
    if last_row_id == 0 and count == 0:
        log.info("audit_export_skipped_empty_log")
        return None

    signing_key = load_signing_key(settings.audit_signing_key)
    signing_ts = datetime.now(tz=UTC)
    checkpoint_id = signing_ts.date().isoformat()
    signature = signing_key.sign(last_row_hash)
    record = CheckpointRecord(
        checkpoint_id=checkpoint_id,
        last_row_id=last_row_id,
        last_row_hash=last_row_hash,
        signature=signature,
        signing_ts=signing_ts,
        count=count,
    )
    body = checkpoint_to_json(record)
    object_key = f"checkpoints/{checkpoint_id}.json"
    s3_uri = upload_checkpoint_json(settings, object_key=object_key, body=body)
    await insert_checkpoint_row(dsn, record=record, s3_uri=s3_uri)
    log.info(
        "audit_nightly_export_complete",
        checkpoint_id=checkpoint_id,
        last_row_id=last_row_id,
        count=count,
    )
    return record


def schedule_nightly_export(settings: Settings, scheduler: AsyncIOScheduler) -> None:
    """Register UTC cron job on an APScheduler instance."""
    from apscheduler.triggers.cron import CronTrigger

    async def _job() -> None:
        try:
            await run_nightly_export(settings)
        except Exception as exc:  # noqa: BLE001
            log.error("audit_nightly_export_failed", error=str(exc))

    scheduler.add_job(
        _job,
        trigger=CronTrigger(
            hour=settings.export_cron_hour,
            minute=settings.export_cron_minute,
            timezone="UTC",
        ),
        id="audit_nightly_export",
        replace_existing=True,
    )
