"""Ingestion orchestration: adapters → Postgres → Parquet → NATS."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from typing import Any

import nats
import polars as pl
import structlog
from zinc_schemas.ingestion import Record

from data_ingestion.adapters import get_adapter
from data_ingestion.adapters.base import _YFINANCE_EXCHANGES, load_active_instruments
from data_ingestion.adapters.fred import FredAdapter
from data_ingestion.adapters.yfinance import YfinanceAdapter
from data_ingestion.observability import (
    observe_duration,
    record_error,
    record_success,
    span,
    traced_fetch,
)
from data_ingestion.writers.parquet_writer import ParquetWriter
from data_ingestion.writers.postgres_writer import PostgresWriter, get_pool

log = structlog.get_logger()

MARKETS: tuple[str, ...] = ("US", "HK", "JP", "TW", "CN")
DEFAULT_ADAPTER_NAMES: tuple[str, ...] = (
    "yfinance",
    "fred",
    "alpaca_data",
    "cn_proxy",
    "news",
)


async def _fetch_adapter_records(adapter_name: str, target_date: date) -> list[Record]:
    """Collect all records from one adapter with tracing."""
    adapter = get_adapter(adapter_name)

    async def _collect() -> list[Record]:
        return [record async for record in adapter.fetch(target_date)]

    return await traced_fetch(adapter_name, "all", _collect)


class IngestionPipeline:
    """End-to-end daily ingest: parallel adapters, Postgres, Parquet, NATS."""

    def __init__(
        self,
        *,
        parquet_writer: ParquetWriter | None = None,
        upsert: bool = False,
    ) -> None:
        self._parquet = parquet_writer or ParquetWriter()
        self._upsert = upsert

    async def run(
        self,
        target_date: date,
        *,
        adapter_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a full ingestion day inside one DB transaction.

        Steps:
            1. Parallel adapter fetch
            2. COPY into Postgres (rollback on failure)
            3. Per-market Parquet snapshots + catalog rows
            4. NATS ``data.snapshots.{market}.{date}`` events

        Args:
            target_date: Trading calendar date to ingest.
            adapter_names: Adapters to run (default: all five).

        Returns:
            Summary dict with per-adapter and per-market results.
        """
        names = adapter_names or list(DEFAULT_ADAPTER_NAMES)
        pool = await get_pool()
        summary: dict[str, Any] = {
            "date": str(target_date),
            "adapters": names,
            "adapter_results": {},
            "snapshots": {},
            "nats_events": [],
        }

        async with observe_duration("pipeline", "all"):
            async with span("pipeline.run", date=str(target_date)):
                fetch_tasks = {
                    name: asyncio.create_task(_fetch_adapter_records(name, target_date))
                    for name in names
                }
                records_by_adapter: dict[str, list[Record]] = {}
                for name, task in fetch_tasks.items():
                    try:
                        records_by_adapter[name] = await task
                        summary["adapter_results"][name] = {
                            "records_fetched": len(records_by_adapter[name]),
                        }
                    except Exception as exc:  # noqa: BLE001
                        record_error(name, type(exc).__name__)
                        raise

                all_records: list[Record] = []
                for batch in records_by_adapter.values():
                    all_records.extend(batch)

                async with pool.acquire() as conn, conn.transaction():
                    writer = PostgresWriter(conn, upsert=self._upsert)
                    try:
                        written = await writer.write_records(
                            all_records,
                            adapter="pipeline",
                            market="all",
                        )
                        summary["written"] = written

                        for market in MARKETS:
                            rows = await writer.fetch_market_daily_frame(market, target_date)
                            if not rows:
                                continue
                            frame = pl.DataFrame([dict(row) for row in rows])
                            snapshot = await self._parquet.write_daily_snapshot(
                                market,
                                target_date,
                                frame,
                            )
                            await writer.register_snapshot(
                                market=market,
                                trade_date=target_date,
                                blob_uri=snapshot.blob_uri,
                                sha256_hex=snapshot.sha256_hex,
                                row_count=snapshot.row_count,
                            )
                            summary["snapshots"][market] = {
                                "blob_uri": snapshot.blob_uri,
                                "row_count": snapshot.row_count,
                                "sha256": snapshot.sha256_hex,
                            }
                    except Exception as exc:  # noqa: BLE001
                        record_error("pipeline", type(exc).__name__)
                        log.error("pipeline_transaction_failed", error=str(exc))
                        raise

                nats_url = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
                nc = await nats.connect(nats_url)
                js = nc.jetstream()
                try:
                    for market, meta in summary["snapshots"].items():
                        subject = f"data.snapshots.{market}.{target_date.isoformat()}"
                        payload = json.dumps(
                            {
                                "market": market,
                                "date": str(target_date),
                                "blob_uri": meta["blob_uri"],
                                "row_count": meta["row_count"],
                                "sha256": meta["sha256"],
                            },
                        ).encode()
                        await js.publish(subject, payload)
                        summary["nats_events"].append(subject)
                        record_success(market)
                finally:
                    await nc.close()

        log.info("pipeline_run_complete", **summary)
        return summary


async def run_adapter(adapter_name: str, target_date: date) -> dict[str, Any]:
    """Fetch one adapter and persist (no Parquet/NATS)."""
    records = await _fetch_adapter_records(adapter_name, target_date)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        written = await PostgresWriter(conn).write_records(
            records,
            adapter=adapter_name,
            market="all",
        )
    return {
        "adapter": adapter_name,
        "date": str(target_date),
        "records_fetched": len(records),
        "written": written,
    }


async def ingest_prices(target_date: date) -> dict[str, Any]:
    """Ingest daily OHLCV via the yfinance adapter."""
    summary = await run_adapter("yfinance", target_date)
    instruments = await load_active_instruments(exchange_codes=_YFINANCE_EXCHANGES)
    written_prices = summary["written"].get("prices_daily", 0)
    return {
        "adapter": "yfinance",
        "date": str(target_date),
        "requested": len(instruments),
        "written": written_prices,
        "skipped": max(0, len(instruments) - written_prices),
    }


async def ingest_macro(target_date: date, lookback_days: int = 30) -> dict[str, Any]:
    """Ingest macro series via the FRED adapter."""
    adapter = FredAdapter(lookback_days=lookback_days)
    records = [record async for record in adapter.fetch(target_date)]
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        written = await PostgresWriter(conn).write_records(records, adapter="fred", market="all")
    return {
        "adapter": "fred",
        "series": len(adapter._series_codes),
        "points_written": written.get("macro_indicators", 0),
    }


async def backfill_prices(start: date, end: date) -> dict[str, Any]:
    """Backfill daily prices using yfinance range fetch with upsert."""
    instruments = await load_active_instruments()
    yf_instruments = [i for i in instruments if str(i["exchange_code"]) in _YFINANCE_EXCHANGES]
    adapter = YfinanceAdapter(yf_instruments)
    bars = [bar async for bar in adapter.fetch_daily_range(yf_instruments, start, end)]
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        written = await PostgresWriter(conn, upsert=True).write_prices_daily(bars)
    return {
        "adapter": adapter.name,
        "start": str(start),
        "end": str(end),
        "requested": len(yf_instruments),
        "written": written,
    }


async def backfill_macro(start: date, end: date) -> dict[str, Any]:
    """Backfill macro indicators over a date range."""
    adapter = FredAdapter()
    records = [record async for record in adapter.fetch(end, start=start)]
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        written = await PostgresWriter(conn, upsert=True).write_records(
            records,
            adapter="fred",
            market="all",
        )
    return {
        "adapter": adapter.name,
        "start": str(start),
        "end": str(end),
        "series": len(adapter._series_codes),
        "points_written": written.get("macro_indicators", 0),
    }


async def run_all_adapters(target_date: date) -> dict[str, Any]:
    """Run the full ingestion pipeline for all adapters."""
    pipeline = IngestionPipeline()
    return await pipeline.run(target_date)
