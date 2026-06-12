"""15-minute delayed intraday bars into theeyebeta.prices_intraday."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import httpx
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.massive_providers import MASSIVE_BASE_URL, UniverseInstrument

log = structlog.get_logger()

MARKET_OPEN_UTC = time(13, 30)
MARKET_CLOSE_UTC = time(20, 45)
PLAN_DELAY_MINUTES = 15
BUCKET_MINUTES = 15
COVERAGE_WARN_THRESHOLD = 0.90
INSERT_BATCH = 200


def floor_bucket(ts: datetime, *, delay_minutes: int = PLAN_DELAY_MINUTES) -> datetime:
    """Latest safe bucket = now - delay, floored to :00/:15/:30/:45 UTC."""
    safe = ts.astimezone(UTC) - timedelta(minutes=delay_minutes)
    minute = (safe.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return safe.replace(minute=minute, second=0, microsecond=0)


def is_market_session(now: datetime) -> bool:
    """Mon-Fri 13:30-20:45 UTC."""
    local = now.astimezone(UTC)
    if local.weekday() >= 5:
        return False
    t = local.time()
    return MARKET_OPEN_UTC <= t <= MARKET_CLOSE_UTC


async def load_universe(conn: asyncpg.Connection) -> list[UniverseInstrument]:
    """Active mapped instruments."""
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


def validate_bar(row: dict[str, Any]) -> bool:
    """Reject invalid OHLC rows."""
    try:
        o, h, l, c = float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"])
    except (KeyError, TypeError, ValueError):
        return False
    if h < l or min(o, h, l, c) <= 0:
        return False
    return True


async def fetch_bucket_bar(
    client: httpx.AsyncClient,
    symbol: str,
    bucket: datetime,
) -> dict[str, Any] | None:
    """Fetch one 15m bar for symbol at bucket (Massive aggs API)."""
    day = bucket.date().isoformat()
    path = f"/v2/aggs/ticker/{symbol}/range/15/minute/{day}/{day}"
    resp = await client.get(
        path,
        params={"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    if resp.status_code != 200:
        return None
    payload = resp.json()
    target_ms = int(bucket.timestamp() * 1000)
    for result in payload.get("results", []):
        if int(result.get("t", 0)) == target_ms:
            return result
    return None


class IntradayIngestionWorker(BaseWorker):
    """Ingest 15-min delayed bars; never touches prices_daily."""

    worker_name = "IntradayIngestionWorker"
    worker_type = "intraday_prices"
    display_name = "Intraday Ingestion"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        now = datetime.now(UTC)
        if not is_market_session(now):
            return WorkerResult(
                records_written=0,
                metadata={"skipped": True, "reason": "outside market hours"},
            )

        bucket = floor_bucket(now)
        universe = await load_universe(conn)
        max_ts = await conn.fetchval("SELECT MAX(ts) FROM theeyebeta.prices_intraday")
        if max_ts is not None and bucket <= max_ts:
            return WorkerResult(
                records_written=0,
                metadata={"skipped": True, "reason": "no new buckets", "bucket": bucket.isoformat()},
            )

        api_key = os.environ.get("MASSIVE_API_KEY")
        if not api_key and not dry_run:
            msg = "MASSIVE_API_KEY is not set"
            raise RuntimeError(msg)

        written = 0
        rejected = 0
        planned = 0

        async with httpx.AsyncClient(
            base_url=MASSIVE_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        ) as client:
            for inst in universe:
                if dry_run:
                    planned += 1
                    continue
                raw = await fetch_bucket_bar(client, inst.symbol, bucket)
                if raw is None or not validate_bar(raw):
                    rejected += 1
                    continue
                await conn.execute(
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
                    inst.instrument_id,
                    bucket,
                    Decimal(str(raw["o"])),
                    Decimal(str(raw["h"])),
                    Decimal(str(raw["l"])),
                    Decimal(str(raw["c"])),
                    int(raw.get("v") or 0),
                    "massive_intraday_15m",
                )
                written += 1

        coverage = written / len(universe) if universe else 0.0
        metadata: dict[str, Any] = {
            "bucket": bucket.isoformat(),
            "universe": len(universe),
            "written": written,
            "rejected": rejected,
            "coverage": round(coverage, 4),
            "dry_run": dry_run,
            "planned": planned,
        }
        if coverage < COVERAGE_WARN_THRESHOLD and not dry_run and universe:
            log.warning("intraday_coverage_low", **metadata)

        return WorkerResult(
            records_written=written if not dry_run else planned,
            records_expected=len(universe),
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    worker = IntradayIngestionWorker()
    target = date.fromisoformat(args.date) if args.date else date.today()
    result = await worker.run(
        target,
        run_type="manual" if args.once else "scheduled",
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday 15m ingestion worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", help="Anchor trade date YYYY-MM-DD")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
