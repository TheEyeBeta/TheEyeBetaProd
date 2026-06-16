"""Data quality queries — unacknowledged CRITICAL gap alerts."""

from __future__ import annotations

import asyncpg


async def fetch_unacknowledged_critical_gap_symbols(conn: asyncpg.Connection) -> list[str]:
    """Return instrument symbols with open CRITICAL data-gap alerts."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT COALESCE(a.message, a.title) AS label
          FROM theeyebeta.audit_alerts a
         WHERE a.severity = 'CRITICAL'
           AND a.acknowledged_at IS NULL
           AND a.resolved_at IS NULL
           AND (
             a.title ILIKE '%gap%'
             OR a.message ILIKE '%data_gap%'
             OR a.worker_name ILIKE '%sentinel%'
           )
         ORDER BY 1
         LIMIT 100
        """,
    )
    symbols: list[str] = []
    for row in rows:
        label = str(row["label"])
        if label and label not in symbols:
            symbols.append(label)
    return symbols


async def count_unacknowledged_critical_gaps(conn: asyncpg.Connection) -> int:
    """Count open CRITICAL gap-related alerts."""
    count = await conn.fetchval(
        """
        SELECT COUNT(*)::int
          FROM theeyebeta.audit_alerts
         WHERE severity = 'CRITICAL'
           AND acknowledged_at IS NULL
           AND resolved_at IS NULL
           AND (title ILIKE '%gap%' OR worker_name ILIKE '%sentinel%')
        """,
    )
    return int(count or 0)
