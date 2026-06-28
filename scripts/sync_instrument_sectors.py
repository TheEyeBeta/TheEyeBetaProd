#!/usr/bin/env python3
# ruff: noqa: E402
"""Sync theeyebeta.instruments.sector from public fundamentals and Massive SIC data.

CLI:
    uv run python scripts/sync_instrument_sectors.py --from-public --apply
    uv run python scripts/sync_instrument_sectors.py --massive --apply
    uv run python scripts/sync_instrument_sectors.py --yfinance --apply
    uv run python scripts/sync_instrument_sectors.py --apply   # public + massive + yfinance
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import worker_database_url
from workers.market_cap_providers import (
    CAP_THRESHOLD_USD,
    DEFAULT_FETCH_CONCURRENCY,
    MassiveReferenceClient,
    fetch_massive_instrument_tags,
    fetch_yfinance_sectors,
)

log = structlog.get_logger()

SYNC_FROM_PUBLIC_SQL = """
UPDATE theeyebeta.instruments i
   SET sector = src.sector,
       updated_at = now()
  FROM (
        SELECT m.instrument_id,
               COALESCE(NULLIF(fc.sector, ''), s.sector_name) AS sector
          FROM theeyebeta.public_ticker_map m
          JOIN theeyebeta.instruments inst ON inst.id = m.instrument_id
          LEFT JOIN public.fundamentals_company fc ON fc.ticker_id = m.public_ticker_id
          LEFT JOIN public.ticker_profile tp ON tp.ticker_id = m.public_ticker_id
          LEFT JOIN public.sectors s ON s.sector_id = tp.sector_id
         WHERE inst.active
           AND COALESCE(NULLIF(fc.sector, ''), s.sector_name) IS NOT NULL
           AND COALESCE(NULLIF(fc.sector, ''), s.sector_name) <> ''
       ) src
 WHERE i.id = src.instrument_id
   AND (i.sector IS NULL OR i.sector = '' OR i.sector IS DISTINCT FROM src.sector)
"""


async def sync_from_public(conn: asyncpg.Connection, *, dry_run: bool) -> int:
    """Copy sector labels from public fundamentals / ticker_profile."""
    if dry_run:
        return int(
            await conn.fetchval(
                """
                SELECT COUNT(DISTINCT m.instrument_id)
                  FROM theeyebeta.public_ticker_map m
                  JOIN theeyebeta.instruments inst ON inst.id = m.instrument_id
                  LEFT JOIN public.fundamentals_company fc ON fc.ticker_id = m.public_ticker_id
                  LEFT JOIN public.ticker_profile tp ON tp.ticker_id = m.public_ticker_id
                  LEFT JOIN public.sectors s ON s.sector_id = tp.sector_id
                 WHERE inst.active
                   AND COALESCE(NULLIF(fc.sector, ''), s.sector_name) IS NOT NULL
                   AND COALESCE(NULLIF(fc.sector, ''), s.sector_name) <> ''
                   AND (inst.sector IS NULL OR inst.sector = ''
                        OR inst.sector IS DISTINCT FROM COALESCE(NULLIF(fc.sector, ''), s.sector_name))
                """,
            )
            or 0,
        )
    result = await conn.execute(SYNC_FROM_PUBLIC_SQL)
    return int(result.split()[-1]) if result else 0


async def _symbols_missing_sector(
    conn: asyncpg.Connection,
    *,
    min_cap: float,
    equity_only: bool = False,
) -> list[tuple[int, str]]:
    cap_date = await conn.fetchval("SELECT MAX(as_of_date) FROM theeyebeta.market_cap_daily")
    if cap_date is None:
        return []
    equity_filter = "AND i.asset_class IN ('equity', 'adr')" if equity_only else ""
    rows = await conn.fetch(
        f"""
        SELECT i.id AS instrument_id, i.symbol
          FROM theeyebeta.instruments i
          JOIN theeyebeta.market_cap_daily c
            ON c.symbol = i.symbol AND c.as_of_date = $1
         WHERE i.active
           AND c.market_cap >= $2
           AND (i.sector IS NULL OR i.sector = '')
           {equity_filter}
         ORDER BY i.symbol
        """,
        cap_date,
        min_cap,
    )
    return [(int(r["instrument_id"]), str(r["symbol"])) for r in rows]


async def _apply_tag_updates(
    conn: asyncpg.Connection,
    rows: list[tuple[int, str | None, str | None]],
) -> int:
    """Apply sector and optional asset_class updates."""
    if not rows:
        return 0
    await conn.executemany(
        """
        UPDATE theeyebeta.instruments
           SET sector = COALESCE($2::text, sector),
               asset_class = COALESCE($3::text, asset_class),
               updated_at = now()
         WHERE id = $1
           AND (
                ($2::text IS NOT NULL AND (sector IS NULL OR sector = '' OR sector IS DISTINCT FROM $2::text))
                OR ($3::text IS NOT NULL AND asset_class IS DISTINCT FROM $3::text)
           )
        """,
        rows,
    )
    return len(rows)


async def sync_from_massive(
    conn: asyncpg.Connection,
    *,
    min_cap: float,
    dry_run: bool,
    concurrency: int,
) -> int:
    """Fill missing sectors via Massive SIC mapping and ticker-type buckets (ETF/Fund)."""
    pending = await _symbols_missing_sector(conn, min_cap=min_cap)
    if dry_run:
        return len(pending)
    if not pending:
        return 0

    client = MassiveReferenceClient()
    try:
        updated = 0
        for chunk_start in range(0, len(pending), 100):
            chunk = pending[chunk_start : chunk_start + 100]
            symbols = [sym for _, sym in chunk]
            symbol_to_id = {sym: iid for iid, sym in chunk}
            tag_map = await fetch_massive_instrument_tags(
                client,
                symbols,
                concurrency=concurrency,
            )
            rows = [
                (
                    symbol_to_id[symbol],
                    meta.sector,
                    meta.asset_class,
                )
                for symbol, meta in tag_map.items()
                if symbol in symbol_to_id and (meta.sector or meta.asset_class)
            ]
            updated += await _apply_tag_updates(conn, rows)
            log.info(
                "massive_sector_chunk",
                done=min(chunk_start + 100, len(pending)),
                total=len(pending),
                updated=updated,
            )
        return updated
    finally:
        await client.aclose()


async def sync_from_yfinance(
    conn: asyncpg.Connection,
    *,
    min_cap: float,
    dry_run: bool,
    min_interval_seconds: float,
) -> int:
    """Fill missing GICS sectors for equity/ADR names via yfinance profiles."""
    pending = await _symbols_missing_sector(conn, min_cap=min_cap, equity_only=True)
    if dry_run:
        return len(pending)
    if not pending:
        return 0

    updated = 0
    for chunk_start in range(0, len(pending), 50):
        chunk = pending[chunk_start : chunk_start + 50]
        symbols = [sym for _, sym in chunk]
        symbol_to_id = {sym: iid for iid, sym in chunk}
        sectors = await fetch_yfinance_sectors(
            symbols,
            min_interval_seconds=min_interval_seconds,
        )
        rows = [
            (symbol_to_id[symbol], sector, None)
            for symbol, sector in sectors.items()
            if symbol in symbol_to_id
        ]
        updated += await _apply_tag_updates(conn, rows)
        log.info(
            "yfinance_sector_chunk",
            done=min(chunk_start + 50, len(pending)),
            total=len(pending),
            updated=updated,
        )
    return updated


async def run_sync(
    *,
    from_public: bool,
    massive: bool,
    yfinance: bool,
    min_cap: float,
    dry_run: bool,
    concurrency: int,
    yfinance_interval: float,
) -> dict[str, int]:
    conn = await asyncpg.connect(worker_database_url())
    try:
        summary: dict[str, int] = {}
        if from_public:
            summary["from_public"] = await sync_from_public(conn, dry_run=dry_run)
        if massive:
            summary["massive"] = await sync_from_massive(
                conn,
                min_cap=min_cap,
                dry_run=dry_run,
                concurrency=concurrency,
            )
        if yfinance:
            summary["yfinance"] = await sync_from_yfinance(
                conn,
                min_cap=min_cap,
                dry_run=dry_run,
                min_interval_seconds=yfinance_interval,
            )
        return summary
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync instrument sector tags")
    parser.add_argument("--from-public", action="store_true", help="Copy from public fundamentals")
    parser.add_argument(
        "--massive",
        action="store_true",
        help="Fetch missing sectors via Massive (SIC + ETF/Fund type buckets)",
    )
    parser.add_argument(
        "--yfinance",
        action="store_true",
        help="Fetch missing GICS sectors for equity/ADR via yfinance",
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=CAP_THRESHOLD_USD,
        help="Min market cap for provider passes (default: 500M)",
    )
    parser.add_argument("--concurrency", type=int, default=DEFAULT_FETCH_CONCURRENCY)
    parser.add_argument(
        "--yfinance-interval",
        type=float,
        default=1.0,
        help="Seconds between yfinance profile requests (default: 1.0)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.from_public and not args.massive and not args.yfinance:
        args.from_public = True
        if args.apply:
            args.massive = True
            args.yfinance = True

    dry_run = not args.apply
    summary = asyncio.run(
        run_sync(
            from_public=args.from_public,
            massive=args.massive,
            yfinance=args.yfinance,
            min_cap=args.min_cap,
            dry_run=dry_run,
            concurrency=args.concurrency,
            yfinance_interval=args.yfinance_interval,
        ),
    )
    print(summary)


if __name__ == "__main__":
    main()
