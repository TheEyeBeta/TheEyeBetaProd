"""15-minute delayed intraday bars into theeyebeta.prices_intraday.

Uses parallel Massive per-ticker 15m range calls (unlimited plan). Only symbols
at or above the $500M intraday tier are fetched; sub-$500M names receive EOD
prices only via the nightly Massive ingest.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.intraday_providers import (
    DEFAULT_INTRADAY_CONCURRENCY,
    MassiveIntradayClient,
)
from workers.universe_tiers import (
    CAP_INTRADAY_THRESHOLD_USD,
    load_intraday_universe,
    resolve_latest_cap_date,
)

log = structlog.get_logger()

MARKET_OPEN_UTC = time(13, 30)
MARKET_CLOSE_UTC = time(20, 0)
PLAN_DELAY_MINUTES = 15
BUCKET_MINUTES = 15
COVERAGE_WARN_THRESHOLD = 0.99
INSERT_BATCH = 500
INTRADAY_SOURCE = "massive_intraday_15m"


def floor_bucket(ts: datetime, *, delay_minutes: int = PLAN_DELAY_MINUTES) -> datetime:
    """Latest safe bucket = now - delay, floored to :00/:15/:30/:45 UTC."""
    safe = ts.astimezone(UTC) - timedelta(minutes=delay_minutes)
    minute = (safe.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return safe.replace(minute=minute, second=0, microsecond=0)


def is_market_session(now: datetime) -> bool:
    """Mon-Fri 13:30-20:00 UTC."""
    local = now.astimezone(UTC)
    if local.weekday() >= 5:
        return False
    t = local.time()
    return MARKET_OPEN_UTC <= t <= MARKET_CLOSE_UTC


def parse_bucket_arg(raw: str) -> datetime:
    """Parse an ISO bucket timestamp."""
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def insert_intraday_batch(
    conn: asyncpg.Connection,
    rows: list[tuple[int, datetime, Decimal, Decimal, Decimal, Decimal, int, str]],
) -> int:
    """Bulk upsert intraday bars; return rows touched."""
    if not rows:
        return 0
    written = 0
    for offset in range(0, len(rows), INSERT_BATCH):
        batch = rows[offset : offset + INSERT_BATCH]
        await conn.executemany(
            """
            INSERT INTO theeyebeta.prices_intraday
                (instrument_id, ts, open, high, low, close, volume, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (instrument_id, ts) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                source = EXCLUDED.source,
                ingested_at = now()
            """,
            batch,
        )
        written += len(batch)
    return written


class IntradayIngestionWorker(BaseWorker):
    """Ingest 15-min delayed bars via parallel Massive batch fetch."""

    worker_name = "IntradayIngestionWorker"
    worker_type = "intraday_prices"
    display_name = "Intraday Ingestion"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        massive_client: MassiveIntradayClient | None = None,
        force: bool = False,
        bucket_override: datetime | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
        self._massive = massive_client
        self._force = force
        self._bucket_override = bucket_override

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        now = datetime.now(UTC)
        if not self._force and not is_market_session(now):
            return WorkerResult(
                records_written=0,
                metadata={"skipped": True, "reason": "outside market hours"},
            )

        bucket = self._bucket_override or floor_bucket(now)
        cap_date = await resolve_latest_cap_date(conn, trade_date)
        universe = await load_intraday_universe(conn)
        if not universe:
            return WorkerResult(
                records_written=0, metadata={"skipped": True, "reason": "empty intraday universe"}
            )

        if not self._bucket_override:
            max_ts = await conn.fetchval("SELECT MAX(ts) FROM theeyebeta.prices_intraday")
            if max_ts is not None and bucket <= max_ts:
                return WorkerResult(
                    records_written=0,
                    metadata={
                        "skipped": True,
                        "reason": "no new buckets",
                        "bucket": bucket.isoformat(),
                    },
                )

        if dry_run and not os.environ.get("MASSIVE_API_KEY") and self._massive is None:
            return WorkerResult(
                records_written=0,
                records_expected=len(universe),
                metadata={
                    "dry_run": True,
                    "bucket": bucket.isoformat(),
                    "universe": len(universe),
                    "planned": len(universe),
                    "fetch_mode": "parallel_batch",
                },
            )

        symbol_map = {inst.symbol.upper(): inst for inst in universe}
        concurrency = int(
            os.environ.get("INTRADAY_FETCH_CONCURRENCY", DEFAULT_INTRADAY_CONCURRENCY),
        )

        massive = self._massive or MassiveIntradayClient()
        own_client = self._massive is None
        try:
            fetched = await massive.fetch_bucket_batch(
                list(symbol_map),
                bucket,
                concurrency=concurrency,
            )
        finally:
            if own_client:
                await massive.aclose()

        bind_rows: list[tuple[int, datetime, Decimal, Decimal, Decimal, Decimal, int, str]] = []
        rejected = 0
        for symbol, inst in symbol_map.items():
            bar = fetched.get(symbol)
            if bar is None:
                rejected += 1
                continue
            bind_rows.append(
                (
                    inst.instrument_id,
                    bucket,
                    Decimal(str(bar.open)),
                    Decimal(str(bar.high)),
                    Decimal(str(bar.low)),
                    Decimal(str(bar.close)),
                    bar.volume,
                    INTRADAY_SOURCE,
                ),
            )

        if dry_run:
            coverage = len(bind_rows) / len(universe) if universe else 0.0
            metadata: dict[str, Any] = {
                "bucket": bucket.isoformat(),
                "universe": len(universe),
                "planned": len(bind_rows),
                "rejected": rejected,
                "coverage": round(coverage, 4),
                "dry_run": True,
                "fetch_mode": "parallel_batch",
                "concurrency": concurrency,
                "tier": "intraday",
                "cap_as_of_date": cap_date.isoformat(),
                "intraday_threshold_usd": CAP_INTRADAY_THRESHOLD_USD,
            }
            return WorkerResult(
                records_written=0,
                records_expected=len(universe),
                metadata=metadata,
            )

        written = await insert_intraday_batch(conn, bind_rows)
        coverage = written / len(universe) if universe else 0.0
        metadata = {
            "bucket": bucket.isoformat(),
            "universe": len(universe),
            "written": written,
            "rejected": rejected,
            "coverage": round(coverage, 4),
            "dry_run": False,
            "fetch_mode": "parallel_batch",
            "concurrency": concurrency,
            "tier": "intraday",
            "cap_as_of_date": cap_date.isoformat(),
            "intraday_threshold_usd": CAP_INTRADAY_THRESHOLD_USD,
        }
        if coverage < COVERAGE_WARN_THRESHOLD and universe:
            log.warning("intraday_coverage_low", **metadata)
        log.info("intraday_ingest_complete", **metadata)
        return WorkerResult(
            records_written=written,
            records_expected=len(universe),
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    bucket_override = parse_bucket_arg(args.bucket) if args.bucket else None
    worker = IntradayIngestionWorker(force=args.force, bucket_override=bucket_override)
    target = date.fromisoformat(args.date) if args.date else date.today()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Intraday 15m ingestion worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Run outside market hours")
    parser.add_argument("--date", help="Anchor trade date YYYY-MM-DD")
    parser.add_argument(
        "--bucket",
        help="Explicit bucket ISO timestamp (testing/backfill)",
    )
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
        help="Default manual; systemd passes --run-type scheduled explicitly",
    )
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
