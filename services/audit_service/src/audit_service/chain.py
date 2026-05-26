"""Hash-chained audit_log append and verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog

log = structlog.get_logger()

GENESIS_SEED = b"theeyebeta-genesis-2026-05-21"
GENESIS_HASH = hashlib.sha256(GENESIS_SEED).digest()
_ADVISORY_LOCK_KEY = 7110


def compute_row_hash(prev_hash: bytes, row_payload_canonical_json: str) -> bytes:
    """Return SHA-256 digest chaining ``prev_hash`` and canonical row JSON."""
    material = prev_hash + row_payload_canonical_json.encode("utf-8")
    return hashlib.sha256(material).digest()


def canonical_row_json(
    *,
    ts: datetime,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> str:
    """Build deterministic JSON used for hash chaining."""
    body = {
        "ts": ts.astimezone(UTC).isoformat(),
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class AuditRow:
    """One ``audit_log`` row for verification."""

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    prev_hash: bytes | None
    row_hash: bytes


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of chain verification over a time range."""

    status: str
    rows_checked: int
    first_bad_row_id: int | None = None
    detail: str | None = None


async def append_chained_row(
    dsn: str,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    ts: datetime | None = None,
) -> int:
    """Append one hash-chained row under an advisory lock."""
    event_ts = ts or datetime.now(tz=UTC)
    canonical = canonical_row_json(
        ts=event_ts,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    async with await psycopg.AsyncConnection.connect(dsn) as conn, conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (_ADVISORY_LOCK_KEY,),
        )
        cur = await conn.execute(
            """
                SELECT row_hash
                  FROM theeyebeta.audit_log
                 ORDER BY id DESC
                 LIMIT 1
                 FOR UPDATE
                """,
        )
        prev_row = await cur.fetchone()
        prev_hash = prev_row[0] if prev_row and prev_row[0] is not None else GENESIS_HASH
        row_hash = compute_row_hash(prev_hash, canonical)
        cur = await conn.execute(
            """
                INSERT INTO theeyebeta.audit_log
                    (ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                RETURNING id
                """,
            (
                event_ts,
                actor,
                action,
                entity_type,
                entity_id,
                json.dumps(payload, sort_keys=True, default=str),
                prev_hash,
                row_hash,
            ),
        )
        inserted = await cur.fetchone()
    row_id = int(inserted[0]) if inserted else 0
    log.info("audit_row_appended", row_id=row_id, action=action, entity_type=entity_type)
    return row_id


async def fetch_rows_in_range(
    dsn: str,
    *,
    from_ts: datetime,
    to_ts: datetime,
) -> list[AuditRow]:
    """Load audit rows ordered by id within a timestamp window."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT id, ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash
              FROM theeyebeta.audit_log
             WHERE ts >= %s AND ts <= %s
             ORDER BY id ASC
            """,
            (from_ts, to_ts),
        )
        rows = await cur.fetchall()
    return [
        AuditRow(
            id=int(r[0]),
            ts=r[1],
            actor=str(r[2]),
            action=str(r[3]),
            entity_type=str(r[4]),
            entity_id=str(r[5]),
            payload=r[6] if isinstance(r[6], dict) else json.loads(r[6]),
            prev_hash=bytes(r[7]) if r[7] is not None else None,
            row_hash=bytes(r[8]),
        )
        for r in rows
    ]


async def fetch_prev_hash_before(dsn: str, from_ts: datetime) -> bytes:
    """Return the row_hash of the last row strictly before ``from_ts``, else genesis."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT row_hash
              FROM theeyebeta.audit_log
             WHERE ts < %s
             ORDER BY id DESC
             LIMIT 1
            """,
            (from_ts,),
        )
        row = await cur.fetchone()
    if row and row[0] is not None:
        return bytes(row[0])
    return GENESIS_HASH


def verify_rows(rows: list[AuditRow], *, initial_prev_hash: bytes) -> VerifyResult:
    """Recompute hashes for an ordered row list."""
    expected_prev = initial_prev_hash
    for row in rows:
        if row.prev_hash != expected_prev:
            return VerifyResult(
                status="MISMATCH",
                rows_checked=0,
                first_bad_row_id=row.id,
                detail="prev_hash does not link to prior row",
            )
        canonical = canonical_row_json(
            ts=row.ts,
            actor=row.actor,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            payload=row.payload,
        )
        expected_row_hash = compute_row_hash(expected_prev, canonical)
        if row.row_hash != expected_row_hash:
            return VerifyResult(
                status="MISMATCH",
                rows_checked=0,
                first_bad_row_id=row.id,
                detail="row_hash does not match recomputed digest",
            )
        expected_prev = row.row_hash
    return VerifyResult(status="OK", rows_checked=len(rows))


async def verify_range(
    dsn: str,
    *,
    from_ts: datetime,
    to_ts: datetime,
) -> VerifyResult:
    """Verify hash chain integrity for all rows in ``[from_ts, to_ts]``."""
    rows = await fetch_rows_in_range(dsn, from_ts=from_ts, to_ts=to_ts)
    if not rows:
        return VerifyResult(status="OK", rows_checked=0)
    initial_prev = await fetch_prev_hash_before(dsn, from_ts)
    return verify_rows(rows, initial_prev_hash=initial_prev)
