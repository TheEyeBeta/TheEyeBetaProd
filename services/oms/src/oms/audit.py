"""Append-only audit_log writes for OMS lifecycle events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog

log = structlog.get_logger()


async def insert_audit_log(
    dsn: str,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    """Insert one immutable audit row."""
    body = json.dumps(payload, sort_keys=True, default=str)
    row_hash = hashlib.sha256(body.encode()).digest()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.audit_log
                (ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                datetime.now(tz=UTC),
                actor,
                action,
                entity_type,
                entity_id,
                body,
                None,
                row_hash,
            ),
        )
        await conn.commit()
    log.info("audit_log_inserted", action=action, entity_type=entity_type, entity_id=entity_id)


async def count_audit_trail(dsn: str, entity_id: str) -> int:
    """Count audit rows for one entity (e2e assertions)."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s
            """,
            (entity_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0
