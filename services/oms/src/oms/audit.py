"""Append-only audit_log writes for OMS lifecycle events."""

from __future__ import annotations

from typing import Any

import psycopg
import structlog
from audit_service.chain import append_chained_row

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
    await append_chained_row(
        dsn,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
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
