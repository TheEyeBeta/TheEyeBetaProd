#!/usr/bin/env python3
"""Backfill theeyebeta.prices_daily for the active universe via Massive grouped-daily.

One API call per trading day (not per symbol). Replaces the slow public SQL mirror
for shallow-history instruments in the $500M+ tier.

CLI:
    uv run python scripts/backfill_prices_massive_active_universe.py --dry-run
    uv run python scripts/backfill_prices_massive_active_universe.py --apply --resume
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

from workers.base_worker import worker_database_url
from workers.massive_providers import (
    MassiveClient,
    UniverseInstrument,
    bar_to_row,
    parse_massive_grouped,
)

log = structlog.get_logger()

DEFAULT_START = date(2021, 6, 7)
CHECKPOINT_PATH = PROD_ROOT / "reports" / "massive_price_backfill_checkpoint.json"
INSERT_BATCH = 500

UPSERT_SQL = """
    INSERT INTO theeyebeta.prices_daily
        (instrument_id, ts, open, high, low, close, adj_close, volume, source)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT (instrument_id, ts) DO NOTHING
"""


async def _trading_dates(conn: asyncpg.Connection, *, start: date, end: date) -> list[date]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT p.date AS d
          FROM public.price_daily_y2021 p
         WHERE p.date BETWEEN $1 AND $2
        UNION
        SELECT DISTINCT p.date
          FROM public.price_daily_y2022 p
         WHERE p.date BETWEEN $1 AND $2
        UNION
        SELECT DISTINCT p.date
          FROM public.price_daily_y2023 p
         WHERE p.date BETWEEN $1 AND $2
        UNION
        SELECT DISTINCT p.date
          FROM public.price_daily_y2024 p
         WHERE p.date BETWEEN $1 AND $2
        UNION
        SELECT DISTINCT p.date
          FROM public.price_daily_y2025 p
         WHERE p.date BETWEEN $1 AND $2
        UNION
        SELECT DISTINCT p.date
          FROM public.price_daily_y2026 p
         WHERE p.date BETWEEN $1 AND $2
         ORDER BY d
        """,
        start,
        end,
    )
    dates = [row["d"] for row in rows]
    if dates:
        return dates
    rows = await conn.fetch(
        """
        SELECT calendar_date AS d
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date BETWEEN $1 AND $2
         ORDER BY calendar_date
        """,
        start,
        end,
    )
    return [row["d"] for row in rows]


async def _load_universe(conn: asyncpg.Connection) -> list[UniverseInstrument]:
    rows = await conn.fetch(
        """
        SELECT i.id AS instrument_id,
               m.public_ticker_id AS ticker_id,
               i.symbol,
               e.code AS exchange_code
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
         WHERE i.active
         ORDER BY i.symbol
        """,
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


def _load_checkpoint(path: Path) -> date | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    raw = payload.get("last_date")
    return date.fromisoformat(raw) if raw else None


def _save_checkpoint(path: Path, trade_date: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_date": trade_date.isoformat()}, indent=2))


async def backfill_prices(
    *,
    start: date,
    end: date,
    dry_run: bool,
    resume: bool,
    checkpoint_path: Path,
) -> dict:
    conn = await asyncpg.connect(worker_database_url())
    massive = MassiveClient()
    try:
        universe = await _load_universe(conn)
        symbol_map = {inst.symbol: inst for inst in universe}
        dates = await _trading_dates(conn, start=start, end=end)
        if resume:
            last = _load_checkpoint(checkpoint_path)
            if last:
                dates = [d for d in dates if d > last]
        log.info(
            "massive_price_backfill_start",
            start=start.isoformat(),
            end=end.isoformat(),
            active=len(universe),
            days=len(dates),
            dry_run=dry_run,
        )

        written_total = 0
        for trade_date in dates:
            payload = await massive.grouped_daily(trade_date)
            bars = parse_massive_grouped(
                payload,
                symbol_map=symbol_map,
                trade_date=trade_date,
            )
            if dry_run:
                written_total += len(bars)
            else:
                bind_rows = [bar_to_row(bar) for bar in bars.values()]
                for offset in range(0, len(bind_rows), INSERT_BATCH):
                    batch = bind_rows[offset : offset + INSERT_BATCH]
                    await conn.executemany(UPSERT_SQL, batch)
                written_total += len(bind_rows)
                _save_checkpoint(checkpoint_path, trade_date)
            log.info(
                "massive_price_day",
                trade_date=trade_date.isoformat(),
                bars=len(bars),
                written_total=written_total,
            )
        return {
            "active_universe": len(universe),
            "days_processed": len(dates),
            "rows_written": written_total,
            "dry_run": dry_run,
        }
    finally:
        await massive.aclose()
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Massive grouped-daily price backfill")
    parser.add_argument("--start", default=DEFAULT_START.isoformat())
    parser.add_argument("--end", default=date(2026, 6, 18).isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint", default=str(CHECKPOINT_PATH))
    args = parser.parse_args()
    summary = asyncio.run(
        backfill_prices(
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            dry_run=not args.apply,
            resume=args.resume,
            checkpoint_path=Path(args.checkpoint),
        ),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
