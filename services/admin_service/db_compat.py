"""Graceful degradation when production DB schema lags admin migrations."""

from __future__ import annotations

from datetime import date
from typing import Any

import asyncpg


async def table_exists(conn: asyncpg.Connection, schema: str, name: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
               WHERE table_schema = $1 AND table_name = $2
            )
            """,
            schema,
            name,
        ),
    )


async def column_exists(
    conn: asyncpg.Connection,
    schema: str,
    table: str,
    column: str,
) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.columns
               WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
            )
            """,
            schema,
            table,
            column,
        ),
    )


async def max_date_column(
    conn: asyncpg.Connection,
    *,
    schema: str,
    table: str,
    candidates: tuple[str, ...] = ("trade_date", "date", "as_of_date", "period_end"),
) -> date | None:
    """Return MAX(column) for the first date-like column that exists."""
    for column in candidates:
        if not await column_exists(conn, schema, table, column):
            continue
        try:
            row = await conn.fetchrow(
                f'SELECT MAX("{column}") AS latest FROM {schema}.{table}',
            )
        except asyncpg.PostgresError:
            continue
        latest = row["latest"] if row else None
        if latest is None:
            return None
        if isinstance(latest, date):
            return latest
        return latest.date() if hasattr(latest, "date") else None
    return None
