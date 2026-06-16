"""Append-only audit_log writes for admin-service mutations."""

from __future__ import annotations

from typing import Any

import structlog
from audit_service.chain import append_chained_row

log = structlog.get_logger()

# DSN is set once at lifespan startup via configure_audit_dsn().
_dsn: str = ""


def configure_audit_dsn(dsn: str) -> None:
    """Store the DB DSN used by write_audit_log. Called in app lifespan."""
    global _dsn
    _dsn = dsn


async def write_audit_log(
    _conn: object,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    """Insert one hash-chained audit row.

    Args:
        _conn: Unused asyncpg connection kept for call-site compatibility.
            The write goes through ``audit_service.chain.append_chained_row``
            which opens its own psycopg connection under the advisory lock that
            guarantees hash-chain integrity.
        actor: Operator identity (e.g. ``admin-api:admin``).
        action: Verb dotted with entity (e.g. ``approve.order``).
        entity_type: Entity table name (e.g. ``order``).
        entity_id: Primary key as string.
        payload: Full request body / mutation context.
    """
    await append_chained_row(
        _dsn,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    log.info(
        "admin_audit_log_written",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
    )
