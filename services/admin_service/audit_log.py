"""Append-only ``audit_log`` writes for admin-service mutations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

log = structlog.get_logger()


async def write_audit_log(
    conn: asyncpg.Connection,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    """Insert one immutable audit row using the caller's DB connection.

    Args:
        conn: Active asyncpg connection (same transaction as the mutation).
        actor: Operator identity (e.g. ``admin-api:admin``).
        action: Verb dotted with entity (e.g. ``approve.order``).
        entity_type: Entity table name (e.g. ``order``).
        entity_id: Primary key as string.
        payload: Full request body / mutation context.
    """
    body = json.dumps(payload, sort_keys=True, default=str)
    row_hash = hashlib.sha256(body.encode()).digest()
    await conn.execute(
        """
        INSERT INTO theeyebeta.audit_log
            (ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
        """,
        datetime.now(tz=UTC),
        actor,
        action,
        entity_type,
        entity_id,
        body,
        None,
        row_hash,
    )
    log.info(
        "admin_audit_log_written",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )
