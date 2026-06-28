#!/usr/bin/env python3
"""Mirror public.price_daily into theeyebeta.prices_daily for the active universe.

Fills shallow price history so native indicator compute can run across the full
$500M+ cap tier. Uses year partitions and skips rows already present.

CLI:
    uv run python scripts/mirror_public_prices_for_active_universe.py --dry-run
    uv run python scripts/mirror_public_prices_for_active_universe.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import worker_database_url  # noqa: E402

log = structlog.get_logger()

DEFAULT_START = date(2021, 6, 7)
MIRROR_SOURCE = "public_mirror_active_universe"


async def _years(conn: asyncpg.Connection, start: date, end: date) -> list[int]:
    years: list[int] = []
    for year in range(start.year, end.year + 1):
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                 WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            f"price_daily_y{year}",
        )
        if exists:
            years.append(year)
    return years


async def mirror_year(
    conn: asyncpg.Connection,
    *,
    year: int,
    start: date,
    end: date,
    dry_run: bool,
) -> int:
    year_start = max(start, date(year, 1, 1))
    year_end = min(end, date(year, 12, 31))
    table = f"public.price_daily_y{year}"
    if dry_run:
        return int(
            await conn.fetchval(
                f"""
                SELECT COUNT(*)
                  FROM {table} p
                  JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = p.ticker_id
                  JOIN theeyebeta.instruments i ON i.id = m.instrument_id AND i.active
                 WHERE p.date BETWEEN $1 AND $2
                """,  # noqa: S608
                year_start,
                year_end,
            )
            or 0,
        )

    result = await conn.execute(
        f"""
        INSERT INTO theeyebeta.prices_daily
            (instrument_id, ts, open, high, low, close, adj_close, volume, source)
        SELECT m.instrument_id,
               p.date::timestamp AT TIME ZONE 'UTC',
               p.open,
               p.high,
               p.low,
               p.close,
               p.adj_close,
               p.volume,
               $3
          FROM {table} p
          JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = p.ticker_id
          JOIN theeyebeta.instruments i ON i.id = m.instrument_id AND i.active
         WHERE p.date BETWEEN $1 AND $2
        ON CONFLICT (instrument_id, ts) DO NOTHING
        """,  # noqa: S608
        year_start,
        year_end,
        MIRROR_SOURCE,
    )
    return int(result.split()[-1]) if result else 0


async def run_mirror(*, start: date, end: date, dry_run: bool) -> dict:
    conn = await asyncpg.connect(worker_database_url())
    try:
        active = await conn.fetchval(
            "SELECT COUNT(*) FROM theeyebeta.instruments WHERE active",
        )
        log.info("mirror_prices_start", start=start.isoformat(), end=end.isoformat(), active=active)
        totals: dict[str, int] = {}
        for year in await _years(conn, start, end):
            written = await mirror_year(conn, year=year, start=start, end=end, dry_run=dry_run)
            totals[str(year)] = written
            log.info("mirror_prices_year", year=year, rows=written, dry_run=dry_run)
        return {"active_universe": int(active or 0), "years": totals, "dry_run": dry_run}
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror public prices for active universe")
    parser.add_argument("--start", default=DEFAULT_START.isoformat())
    parser.add_argument("--end", help="YYYY-MM-DD (default: latest public price)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    end = date.fromisoformat(args.end) if args.end else date(2026, 6, 17)
    summary = asyncio.run(
        run_mirror(
            start=date.fromisoformat(args.start),
            end=end,
            dry_run=not args.apply,
        ),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
