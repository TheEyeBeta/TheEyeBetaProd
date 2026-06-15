"""Shared trading-calendar helpers for theeyebeta.trading_calendar."""

from __future__ import annotations

from datetime import date

import asyncpg


async def is_trading_day(conn: asyncpg.Connection, trade_date: date) -> bool:
    """Return whether ``trade_date`` is a US trading day."""
    value = await conn.fetchval(
        """
        SELECT is_trading_day
          FROM theeyebeta.trading_calendar
         WHERE calendar_date = $1
         LIMIT 1
        """,
        trade_date,
    )
    if value is None:
        return trade_date.weekday() < 5
    return bool(value)


async def resolve_trading_day_on_or_before(
    conn: asyncpg.Connection,
    as_of: date,
) -> date:
    """Return the latest trading day on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date <= $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        as_of,
    )
    if value is None:
        msg = f"No trading day found on or before {as_of.isoformat()}"
        raise RuntimeError(msg)
    return value


async def prior_trading_day(conn: asyncpg.Connection, trade_date: date) -> date | None:
    """Return the previous trading day before ``trade_date``."""
    return await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        trade_date,
    )


async def latest_trading_day_before(
    conn: asyncpg.Connection,
    cutoff: date,
) -> date:
    """Return the most recent trading day strictly before ``cutoff``."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        cutoff,
    )
    if value is None:
        msg = f"No trading day found before {cutoff.isoformat()}"
        raise RuntimeError(msg)
    return value
