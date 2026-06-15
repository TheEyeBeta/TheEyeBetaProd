"""Nightly market-cap snapshot ingestion from Massive reference data."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.market_cap_providers import (
    DEFAULT_FETCH_CONCURRENCY,
    DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
    MassiveReferenceClient,
    fetch_cap_snapshots,
)

log = structlog.get_logger()

INSERT_BATCH = 500
FETCH_CHUNK = 400


async def resolve_target_trade_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest trading day on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
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


async def load_instrument_map(conn: asyncpg.Connection) -> dict[str, int]:
    """Return upper symbol → instrument_id for all instruments."""
    rows = await conn.fetch(
        """
        SELECT id, symbol
          FROM theeyebeta.instruments
         ORDER BY symbol
        """,
    )
    return {str(row["symbol"]).upper(): int(row["id"]) for row in rows}


async def load_active_symbols(conn: asyncpg.Connection) -> set[str]:
    """Return symbols currently active in the canonical universe."""
    rows = await conn.fetch(
        """
        SELECT symbol
          FROM theeyebeta.instruments
         WHERE active
        """,
    )
    return {str(row["symbol"]).upper() for row in rows}


async def upsert_cap_rows(
    conn: asyncpg.Connection,
    trade_date: date,
    rows: list[Any],
    instrument_map: dict[str, int],
) -> int:
    """Bulk upsert cap snapshots; return rows written."""
    if not rows:
        return 0
    written = 0
    for offset in range(0, len(rows), INSERT_BATCH):
        batch = rows[offset : offset + INSERT_BATCH]
        await conn.executemany(
            """
            INSERT INTO theeyebeta.market_cap_daily (
                symbol, instrument_id, as_of_date, market_cap,
                close_price, shares_outstanding, source
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (symbol, as_of_date) DO UPDATE SET
                instrument_id = EXCLUDED.instrument_id,
                market_cap = EXCLUDED.market_cap,
                close_price = EXCLUDED.close_price,
                shares_outstanding = EXCLUDED.shares_outstanding,
                source = EXCLUDED.source,
                fetched_at = now()
            """,
            [
                (
                    row.symbol,
                    row.instrument_id or instrument_map.get(row.symbol),
                    trade_date,
                    Decimal(str(row.market_cap)),
                    Decimal(str(row.close_price)) if row.close_price is not None else None,
                    row.shares_outstanding,
                    "massive",
                )
                for row in batch
            ],
        )
        written += len(batch)
    return written


async def load_existing_symbols(conn: asyncpg.Connection, trade_date: date) -> set[str]:
    """Return symbols already stored for ``trade_date`` (resume support)."""
    rows = await conn.fetch(
        """
        SELECT symbol
          FROM theeyebeta.market_cap_daily
         WHERE as_of_date = $1
        """,
        trade_date,
    )
    return {str(row["symbol"]).upper() for row in rows}


class MarketCapFetchWorker(BaseWorker):
    """Fetch and store daily market-cap snapshots for US common stocks."""

    worker_name = "MarketCapFetchWorker"
    worker_type = "market_cap"
    display_name = "Market Cap Fetch"

    def __init__(
        self,
        *,
        database_url: str | None = None,
        massive_client: MassiveReferenceClient | None = None,
        max_symbols: int | None = None,
    ) -> None:
        super().__init__(database_url=database_url)
        self._massive = massive_client
        self._max_symbols = max_symbols

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        target = await resolve_target_trade_date(conn, trade_date)
        instrument_map = await load_instrument_map(conn)
        active_symbols = await load_active_symbols(conn)

        massive = self._massive or MassiveReferenceClient()
        own_client = self._massive is None
        try:
            grouped_closes = await massive.grouped_daily(target)
            existing = await load_existing_symbols(conn, target)
            symbol_set = (set(grouped_closes) | active_symbols) - existing
            symbols = sorted(symbol_set)
            if self._max_symbols is not None:
                symbols = symbols[: self._max_symbols]

            concurrency = int(
                os.environ.get("MARKET_CAP_FETCH_CONCURRENCY", DEFAULT_FETCH_CONCURRENCY),
            )
            interval = float(
                os.environ.get(
                    "MARKET_CAP_MIN_REQUEST_INTERVAL_SECONDS",
                    DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
                ),
            )

            written_total = 0
            snapshots_total: list[Any] = []
            for offset in range(0, len(symbols), FETCH_CHUNK):
                chunk = symbols[offset : offset + FETCH_CHUNK]
                snapshots = await fetch_cap_snapshots(
                    massive,
                    chunk,
                    grouped_closes=grouped_closes,
                    instrument_ids=instrument_map,
                    concurrency=concurrency,
                    min_interval_seconds=interval,
                )
                snapshots_total.extend(snapshots)
                if not dry_run and snapshots:
                    written_total += await upsert_cap_rows(
                        conn,
                        target,
                        snapshots,
                        instrument_map,
                    )

            ge_threshold = sum(1 for row in snapshots_total if row.market_cap >= 500_000_000)
            metadata: dict[str, Any] = {
                "trade_date": target.isoformat(),
                "symbols_requested": len(symbols),
                "symbols_skipped_existing": len(existing),
                "snapshots_fetched": len(snapshots_total),
                "grouped_closes": len(grouped_closes),
                "above_500m": ge_threshold,
                "dry_run": dry_run,
            }

            if dry_run:
                metadata["sample_symbols"] = [row.symbol for row in snapshots_total[:10]]
                return WorkerResult(
                    records_written=0,
                    records_expected=len(symbols),
                    metadata=metadata,
                )

            metadata["records_written"] = written_total
            log.info("market_cap_fetch_complete", **metadata)
            return WorkerResult(
                records_written=written_total,
                records_expected=len(symbols),
                metadata=metadata,
            )
        finally:
            if own_client:
                await massive.aclose()


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = MarketCapFetchWorker(max_symbols=args.max_symbols)
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    """CLI entrypoint for the market-cap fetch worker."""
    parser = argparse.ArgumentParser(description="Fetch nightly market-cap snapshots")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD; default today")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Limit detail fetches (testing only)",
    )
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
