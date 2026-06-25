"""Load price history from theeyebeta.prices_daily for quant commands."""

from __future__ import annotations

from datetime import date

import asyncpg
import pandas as pd

from tb.lib.db import async_connect
from tb.lib.queries.instruments import resolve_symbol


async def load_active_symbols(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        """
        SELECT UPPER(symbol) AS symbol
          FROM theeyebeta.instruments
         WHERE active = true
        """,
    )
    return {str(r["symbol"]) for r in rows}


async def load_price_frame(
    symbols: list[str],
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 2000,
) -> pd.DataFrame:
    """Return wide DataFrame indexed by date with one close column per symbol."""
    frames: dict[str, pd.Series] = {}
    async with async_connect() as conn:
        for sym in symbols:
            inst = await resolve_symbol(conn, sym)
            if not inst:
                continue
            rows = await conn.fetch(
                """
                SELECT ts::date AS d, close
                  FROM theeyebeta.prices_daily
                 WHERE instrument_id = $1
                   AND ($2::date IS NULL OR ts::date >= $2)
                   AND ($3::date IS NULL OR ts::date <= $3)
                 ORDER BY ts DESC
                 LIMIT $4
                """,
                int(inst["instrument_id"]),
                start,
                end,
                limit,
            )
            if not rows:
                continue
            series = pd.Series(
                {r["d"]: float(r["close"]) for r in reversed(rows)},
                name=sym.upper(),
                dtype=float,
            )
            frames[sym.upper()] = series
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


async def load_indicator_frame(
    symbol: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Daily close + EMA columns for backtests."""
    async with async_connect() as conn:
        inst = await resolve_symbol(conn, symbol)
        if not inst:
            return pd.DataFrame()
        rows = await conn.fetch(
            """
            SELECT p.ts::date AS d, p.close, t.ema_12, t.ema_26, t.sma_50, t.sma_200
              FROM theeyebeta.prices_daily p
              LEFT JOIN theeyebeta.ind_technical_daily t
                ON t.instrument_id = p.instrument_id AND t.date = p.ts::date
             WHERE p.instrument_id = $1
               AND ($2::date IS NULL OR p.ts::date >= $2)
               AND ($3::date IS NULL OR p.ts::date <= $3)
             ORDER BY p.ts
            """,
            int(inst["instrument_id"]),
            start,
            end,
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows]).set_index("d")
