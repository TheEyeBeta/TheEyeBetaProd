"""Two-tier universe helpers: EOD (all tracked caps) vs intraday (>= $500M)."""

from __future__ import annotations

from datetime import date

import asyncpg

from workers.market_cap_providers import CAP_THRESHOLD_USD
from workers.massive_providers import UniverseInstrument

CAP_INTRADAY_THRESHOLD_USD = CAP_THRESHOLD_USD


async def resolve_latest_cap_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest cap snapshot date on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT MAX(as_of_date)
          FROM theeyebeta.market_cap_daily
         WHERE as_of_date <= $1
        """,
        as_of,
    )
    if value is None:
        msg = "No rows in theeyebeta.market_cap_daily; run MarketCapFetchWorker first"
        raise RuntimeError(msg)
    return value


async def load_eod_universe(conn: asyncpg.Connection) -> list[UniverseInstrument]:
    """Active mapped instruments in the EOD tier (any positive market cap)."""
    cap_date = await resolve_latest_cap_date(conn, date.today())
    rows = await conn.fetch(
        """
        SELECT i.id AS instrument_id,
               m.public_ticker_id AS ticker_id,
               i.symbol,
               e.code AS exchange_code
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
          JOIN theeyebeta.market_cap_daily c
            ON c.symbol = i.symbol
           AND c.as_of_date = $1
         WHERE i.active
           AND c.market_cap > 0
         ORDER BY i.symbol
        """,
        cap_date,
    )
    return [
        UniverseInstrument(
            instrument_id=int(r["instrument_id"]),
            ticker_id=int(r["ticker_id"]),
            symbol=str(r["symbol"]),
            exchange_code=str(r["exchange_code"]),
        )
        for r in rows
    ]


async def load_intraday_universe(conn: asyncpg.Connection) -> list[UniverseInstrument]:
    """Active mapped instruments at or above the intraday cap threshold."""
    cap_date = await resolve_latest_cap_date(conn, date.today())
    rows = await conn.fetch(
        """
        SELECT i.id AS instrument_id,
               m.public_ticker_id AS ticker_id,
               i.symbol,
               e.code AS exchange_code
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
          JOIN theeyebeta.market_cap_daily c
            ON c.symbol = i.symbol
           AND c.as_of_date = $1
         WHERE i.active
           AND c.market_cap >= $2
         ORDER BY i.symbol
        """,
        cap_date,
        CAP_INTRADAY_THRESHOLD_USD,
    )
    return [
        UniverseInstrument(
            instrument_id=int(r["instrument_id"]),
            ticker_id=int(r["ticker_id"]),
            symbol=str(r["symbol"]),
            exchange_code=str(r["exchange_code"]),
        )
        for r in rows
    ]
