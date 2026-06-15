"""Backfill macro_regime_snapshots for ARGOS trading-day lookbacks.

Runs ``MacroRegimeWorker`` for each trading day in the lookback window so
30d/5d derived fields can resolve via calendar offsets.

CLI:
    uv run python scripts/backfill_macro_regime.py
    uv run python scripts/backfill_macro_regime.py --days 25 --end-date 2026-06-12
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg
import structlog

from workers.base_worker import worker_database_url
from workers.macro_regime_worker import MacroRegimeWorker

log = structlog.get_logger()

DEFAULT_LOOKBACK_DAYS = 25


async def _trading_days(
    conn: asyncpg.Connection,
    *,
    end_date: date,
    count: int,
) -> list[date]:
    rows = await conn.fetch(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date <= $1
         ORDER BY calendar_date DESC
         LIMIT $2
        """,
        end_date,
        count,
    )
    return sorted(row["calendar_date"] for row in rows)


async def backfill_macro_regime(
    *,
    end_date: date,
    lookback_days: int,
    dry_run: bool,
) -> None:
    """Run macro regime worker for each day in the lookback window."""
    conn = await asyncpg.connect(worker_database_url())
    try:
        days = await _trading_days(conn, end_date=end_date, count=lookback_days)
    finally:
        await conn.close()

    if not days:
        log.warning("no_trading_days", end_date=end_date.isoformat())
        return

    worker = MacroRegimeWorker()
    log.info(
        "backfill_start",
        start=days[0].isoformat(),
        end=days[-1].isoformat(),
        count=len(days),
        dry_run=dry_run,
    )
    for trade_date in days:
        result = await worker.run(trade_date, run_type="recovery", dry_run=dry_run)
        log.info(
            "backfill_day",
            trade_date=trade_date.isoformat(),
            records_written=result.records_written,
            metadata=result.metadata,
        )


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill macro regime snapshots")
    parser.add_argument("--end-date", help="Last trading day to include (YYYY-MM-DD)")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Trading days to backfill (default {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        backfill_macro_regime(
            end_date=_parse_date(args.end_date),
            lookback_days=args.days,
            dry_run=args.dry_run,
        ),
    )


if __name__ == "__main__":
    main()
