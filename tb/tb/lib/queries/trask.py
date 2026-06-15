"""Trask and audit queries."""

from __future__ import annotations

from typing import Any

import asyncpg


async def fetch_trask_components(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """All registered Trask components."""
    rows = await conn.fetch(
        """
        SELECT component_type, component_id, display_name, state, last_heartbeat
          FROM theeyebeta.trask_components
         ORDER BY component_type, component_id
        """,
    )
    return [dict(r) for r in rows]


async def fetch_open_breakers(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Open circuit breakers."""
    rows = await conn.fetch(
        """
        SELECT component_id, state, failure_count, opened_at
          FROM theeyebeta.trask_circuit_breakers
         WHERE state = 'open'
         ORDER BY component_id
        """,
    )
    return [dict(r) for r in rows]


async def fetch_audit_alerts(
    conn: asyncpg.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent audit alerts."""
    rows = await conn.fetch(
        """
        SELECT id, severity, worker_id, message, created_at, resolved_at
          FROM theeyebeta.audit_alerts
         ORDER BY created_at DESC
         LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def fetch_data_gaps(
    conn: asyncpg.Connection,
    *,
    open_only: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Instrument-scoped data gaps."""
    if open_only:
        rows = await conn.fetch(
            """
            SELECT id, instrument_id, gap_type, severity, gap_start, gap_end, detected_at
              FROM theeyebeta.audit_data_gaps
             WHERE resolved_at IS NULL
             ORDER BY detected_at DESC
             LIMIT $1
            """,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, instrument_id, gap_type, severity, gap_start, gap_end, detected_at
              FROM theeyebeta.audit_data_gaps
             ORDER BY detected_at DESC
             LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def fetch_worker_runs(
    conn: asyncpg.Connection,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Recent worker run audit rows."""
    rows = await conn.fetch(
        """
        SELECT worker_name, trade_date, run_type, status, started_at, ended_at
          FROM theeyebeta.worker_runs
         ORDER BY started_at DESC
         LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]
