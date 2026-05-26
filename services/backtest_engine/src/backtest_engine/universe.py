"""Survivorship-bias-free universe construction."""

from __future__ import annotations

from datetime import date

import psycopg
import structlog

log = structlog.get_logger()


def is_symbol_tradable(
    as_of: date,
    *,
    listed_at: date | None,
    delisted_at: date | None,
) -> bool:
    """Point-in-time tradability (survivorship-bias-free membership test)."""
    if listed_at is not None and listed_at > as_of:
        return False
    return not (delisted_at is not None and delisted_at <= as_of)


async def symbols_for_date(
    dsn: str,
    *,
    market: str,
    as_of: date,
    explicit_universe: str | None = None,
) -> list[str]:
    """Return tradable symbols for one historical date.

    Args:
        dsn: Postgres DSN.
        market: Strategy market code (e.g. ``US.NASDAQ``).
        as_of: Point-in-time trade date.
        explicit_universe: Optional comma-separated symbol override.

    Returns:
        Sorted symbol list active and listed on ``as_of``.
    """
    if explicit_universe:
        symbols = [s.strip().upper() for s in explicit_universe.split(",") if s.strip()]
        return sorted(set(symbols))

    exchange_code = _market_to_exchange(market)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT i.symbol
              FROM theeyebeta.instruments i
              JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
             WHERE e.code = %s
               AND (i.listed_at IS NULL OR i.listed_at <= %s)
               AND (i.delisted_at IS NULL OR i.delisted_at > %s)
               AND i.asset_class IN ('equity', 'etf', 'adr')
             ORDER BY i.symbol
            """,
            (exchange_code, as_of, as_of),
        )
        rows = await cur.fetchall()
    symbols = [str(r[0]) for r in rows]
    log.debug("universe_resolved", as_of=str(as_of), count=len(symbols), market=market)
    return symbols


async def union_universe(
    dsn: str,
    *,
    market: str,
    start: date,
    end: date,
    explicit_universe: str | None = None,
) -> list[str]:
    """Union of point-in-time universes across a date range."""
    if explicit_universe:
        return await symbols_for_date(
            dsn,
            market=market,
            as_of=end,
            explicit_universe=explicit_universe,
        )

    exchange_code = _market_to_exchange(market)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT DISTINCT i.symbol
              FROM theeyebeta.instruments i
              JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
             WHERE e.code = %s
               AND (i.listed_at IS NULL OR i.listed_at <= %s)
               AND (i.delisted_at IS NULL OR i.delisted_at > %s)
               AND i.asset_class IN ('equity', 'etf', 'adr')
             ORDER BY 1
            """,
            (exchange_code, end, start),
        )
        rows = await cur.fetchall()
    return [str(r[0]) for r in rows]


def _market_to_exchange(market: str) -> str:
    """Map strategy market string to exchange code."""
    upper = market.upper()
    if "NASDAQ" in upper or upper.startswith("US"):
        return "XNAS"
    if "NYSE" in upper:
        return "XNYS"
    return upper.split(".")[-1] if "." in upper else upper
