#!/usr/bin/env python3
"""TEMPORARY-BRIDGE: mirror theeyebeta.prices_daily into public.price_daily.

Delete in Phase C cutover when the native indicator worker retires legacy compute.
Nothing should write public.price_daily daily after the one-shot massive_backfill;
this bridge keeps the 21:35 legacy pipeline fed until Prompt 7 lands.

CLI examples:
    uv run python scripts/mirror_canonical_prices_to_public.py --dry-run --date 2026-06-09
    uv run python scripts/mirror_canonical_prices_to_public.py --run-type scheduled
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import BaseWorker, WorkerResult  # noqa: E402

log = structlog.get_logger()

CANONICAL_MIRROR_SOURCE = "canonical_mirror"
INSERT_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class MirrorRow:
    """One public.price_daily row sourced from canonical bars."""

    ticker_id: int
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal | None
    volume: int


def dedupe_mirror_rows(rows: list[MirrorRow]) -> list[MirrorRow]:
    """Keep one row per (ticker_id, trade_date); last duplicate wins."""
    unique: dict[tuple[int, date], MirrorRow] = {}
    for row in rows:
        unique[(row.ticker_id, row.trade_date)] = row
    return list(unique.values())


def planned_mirror_writes(
    rows: list[MirrorRow],
    existing_keys: set[tuple[int, date]],
) -> list[MirrorRow]:
    """Return de-duped rows that are not already present in public.price_daily."""
    return [
        row
        for row in dedupe_mirror_rows(rows)
        if (row.ticker_id, row.trade_date) not in existing_keys
    ]


async def resolve_target_trade_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest trading day on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM public.trading_calendar
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


async def load_universe_count(conn: asyncpg.Connection) -> int:
    """Count active instruments mapped to public tickers."""
    value = await conn.fetchval(
        """
        SELECT COUNT(*)
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
         WHERE i.active
        """,
    )
    return int(value or 0)


async def fetch_canonical_rows(
    conn: asyncpg.Connection,
    trade_date: date,
) -> list[MirrorRow]:
    """Load mapped-active canonical bars for ``trade_date``."""
    rows = await conn.fetch(
        """
        SELECT m.public_ticker_id AS ticker_id,
               pd.open,
               pd.high,
               pd.low,
               pd.close,
               pd.adj_close,
               pd.volume
          FROM theeyebeta.prices_daily pd
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = pd.instrument_id
          JOIN theeyebeta.instruments i ON i.id = m.instrument_id AND i.active
         WHERE pd.ts::date = $1
        """,
        trade_date,
    )
    return [
        MirrorRow(
            ticker_id=int(row["ticker_id"]),
            trade_date=trade_date,
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            adj_close=row["adj_close"],
            volume=int(row["volume"]),
        )
        for row in rows
    ]


async def fetch_existing_public_keys(
    conn: asyncpg.Connection,
    trade_date: date,
    ticker_ids: list[int],
) -> set[tuple[int, date]]:
    """Return (ticker_id, date) keys already stored in public.price_daily."""
    if not ticker_ids:
        return set()
    rows = await conn.fetch(
        """
        SELECT ticker_id
          FROM public.price_daily
         WHERE date = $1
           AND ticker_id = ANY($2::bigint[])
        """,
        trade_date,
        ticker_ids,
    )
    return {(int(row["ticker_id"]), trade_date) for row in rows}


async def insert_mirror_batch(conn: asyncpg.Connection, batch: list[MirrorRow]) -> int:
    """Insert one batch with ON CONFLICT DO NOTHING; return rows inserted."""
    if not batch:
        return 0
    written = 0
    for row in batch:
        result = await conn.execute(
            """
            INSERT INTO public.price_daily
                (ticker_id, date, open, high, low, close, adj_close, volume, data_source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (ticker_id, date) DO NOTHING
            """,
            row.ticker_id,
            row.trade_date,
            row.open,
            row.high,
            row.low,
            row.close,
            row.adj_close,
            row.volume,
            CANONICAL_MIRROR_SOURCE,
        )
        if result and result.endswith("1"):
            written += 1
    return written


def build_coverage_metadata(
    *,
    trade_date: date,
    universe_size: int,
    canonical_bars: int,
    planned_writes: int,
    records_written: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Build audit metadata for mirror coverage reporting."""
    coverage = records_written / universe_size if universe_size else 0.0
    return {
        "trade_date": trade_date.isoformat(),
        "universe_size": universe_size,
        "canonical_bars": canonical_bars,
        "planned_writes": planned_writes,
        "records_written": records_written,
        "coverage_ratio": round(coverage, 4),
        "data_source": CANONICAL_MIRROR_SOURCE,
        "dry_run": dry_run,
    }


class CanonicalPriceMirrorWorker(BaseWorker):
    """Mirror canonical daily bars into public.price_daily without overwriting."""

    worker_name = "CanonicalPriceMirror"
    worker_type = "price_mirror"
    display_name = "Canonical Price Mirror"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)
        universe_size = await load_universe_count(conn)
        canonical_rows = await fetch_canonical_rows(conn, target)
        ticker_ids = [row.ticker_id for row in canonical_rows]
        existing_keys = await fetch_existing_public_keys(conn, target, ticker_ids)
        to_write = planned_mirror_writes(canonical_rows, existing_keys)
        planned = len(to_write)

        if dry_run:
            metadata = build_coverage_metadata(
                trade_date=target,
                universe_size=universe_size,
                canonical_bars=len(canonical_rows),
                planned_writes=planned,
                records_written=0,
                dry_run=True,
            )
            print(json.dumps({"worker": self.worker_name, **metadata}, indent=2, sort_keys=True))
            return WorkerResult(
                records_written=0,
                records_expected=universe_size,
                metadata=metadata,
            )

        written = 0
        async with conn.transaction():
            for offset in range(0, len(to_write), INSERT_BATCH_SIZE):
                batch = to_write[offset : offset + INSERT_BATCH_SIZE]
                written += await insert_mirror_batch(conn, batch)

        metadata = build_coverage_metadata(
            trade_date=target,
            universe_size=universe_size,
            canonical_bars=len(canonical_rows),
            planned_writes=planned,
            records_written=written,
            dry_run=False,
        )
        log.info(
            "canonical_price_mirror_complete",
            **metadata,
        )
        print(json.dumps({"worker": self.worker_name, **metadata}, indent=2, sort_keys=True))
        return WorkerResult(
            records_written=written,
            records_expected=universe_size,
            metadata=metadata,
        )


async def _resolve_cli_date(conn: asyncpg.Connection, raw: str | None) -> date:
    if raw:
        return date.fromisoformat(raw)
    return await resolve_target_trade_date(conn, date.today())


async def _async_main(args: argparse.Namespace) -> None:
    worker = CanonicalPriceMirrorWorker()
    conn = await asyncpg.connect(worker.database_url)
    try:
        target_date = await _resolve_cli_date(conn, args.date)
    finally:
        await conn.close()

    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
        records_expected=None,
    )
    if not args.dry_run:
        print(
            json.dumps(
                {
                    "worker": worker.worker_name,
                    "status": "COMPLETED",
                    "records_written": result.records_written,
                    "records_expected": result.records_expected,
                },
                indent=2,
                sort_keys=True,
            ),
        )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Mirror theeyebeta.prices_daily into public.price_daily",
    )
    parser.add_argument(
        "--date",
        help="Target trade date YYYY-MM-DD; default latest trading day",
    )
    parser.add_argument(
        "--run-type",
        default="scheduled",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
