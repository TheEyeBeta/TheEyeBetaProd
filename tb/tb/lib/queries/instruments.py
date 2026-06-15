"""Instrument and price queries."""

from __future__ import annotations

from datetime import date
from typing import Any

import asyncpg


async def resolve_symbol(
    conn: asyncpg.Connection, symbol: str
) -> dict[str, Any] | None:
    """Lookup instrument by symbol (instruments table only)."""
    row = await conn.fetchrow(
        """
        SELECT id AS instrument_id, symbol, active
          FROM theeyebeta.instruments
         WHERE UPPER(symbol) = UPPER($1)
         LIMIT 1
        """,
        symbol,
    )
    return dict(row) if row else None


async def fetch_latest_price(
    conn: asyncpg.Connection, instrument_id: int
) -> dict[str, Any] | None:
    """Latest daily close for an instrument."""
    row = await conn.fetchrow(
        """
        SELECT ts::date AS d, open, high, low, close, volume
          FROM theeyebeta.prices_daily
         WHERE instrument_id = $1
         ORDER BY ts DESC
         LIMIT 1
        """,
        instrument_id,
    )
    return dict(row) if row else None


async def fetch_latest_indicators(
    conn: asyncpg.Connection,
    instrument_id: int,
) -> dict[str, Any] | None:
    """Latest indicator row for an instrument."""
    try:
        row = await conn.fetchrow(
            """
            SELECT date, sma_10, sma_50, sma_200, rsi_14, macd, macd_signal, ema_12, ema_26
              FROM theeyebeta.ind_technical_daily
             WHERE instrument_id = $1
             ORDER BY date DESC
             LIMIT 1
            """,
            instrument_id,
        )
    except asyncpg.InsufficientPrivilegeError:
        return None
    return dict(row) if row else None


async def fetch_price_series(
    conn: asyncpg.Connection,
    instrument_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Daily price series for plotting/export."""
    rows = await conn.fetch(
        """
        SELECT ts::date AS d, open, high, low, close, volume
          FROM theeyebeta.prices_daily
         WHERE instrument_id = $1
           AND ($2::date IS NULL OR ts::date >= $2)
           AND ($3::date IS NULL OR ts::date <= $3)
         ORDER BY ts DESC
         LIMIT $4
        """,
        instrument_id,
        start,
        end,
        limit,
    )
    return [dict(r) for r in reversed(rows)]


async def search_instruments(
    conn: asyncpg.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search instruments by symbol prefix."""
    rows = await conn.fetch(
        """
        SELECT id, symbol, active
          FROM theeyebeta.instruments
         WHERE symbol ILIKE $1
         ORDER BY symbol
         LIMIT $2
        """,
        f"{query}%",
        limit,
    )
    return [dict(r) for r in rows]
