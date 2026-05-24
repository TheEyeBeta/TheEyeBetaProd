"""High-level ingestion pipeline functions called by the CLI.

Each function orchestrates: load instruments/config → fetch via adapter →
write via PostgresWriter → return a summary dict.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog
import yaml

from data_ingestion.adapters.fred_adapter import FREDAdapter
from data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
from data_ingestion.writers.postgres_writer import PostgresWriter

log = structlog.get_logger()

_CONFIG_DIR = Path(__file__).parent / "config"


def _ingest_dsn() -> str:
    """Resolve a psycopg-native DSN from INGEST_DATABASE_URL.

    Returns:
        Plain ``postgresql://`` connection string.

    Raises:
        EnvironmentError: If the variable is unset or empty.
    """
    raw = os.environ.get("INGEST_DATABASE_URL", "")
    if not raw:
        raise EnvironmentError("INGEST_DATABASE_URL is not set")
    return re.sub(r"\+\w+", "", raw, count=1)


async def _load_active_instruments(dsn: str) -> list[dict[str, Any]]:
    """Query theeyebeta.instruments for all active rows with exchange codes.

    Args:
        dsn: psycopg-native connection string.

    Returns:
        List of dicts with keys ``instrument_id``, ``symbol``, ``exchange_code``.
    """
    aconn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    async with aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """
                SELECT i.id, i.symbol, e.code AS exchange_code
                FROM theeyebeta.instruments i
                JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                WHERE i.active = true
                ORDER BY i.symbol
                """
            )
            rows = await cur.fetchall()

    return [
        {"instrument_id": r[0], "symbol": r[1], "exchange_code": r[2]}
        for r in rows
    ]


async def ingest_prices(target_date: date) -> dict[str, Any]:
    """Fetch daily OHLCV prices for all active instruments and persist them.

    Connects to the database using INGEST_DATABASE_URL (tb_app credentials).
    Fetches via YFinanceAdapter with a semaphore of 4 concurrent requests.

    Args:
        target_date: The trading date to ingest prices for.

    Returns:
        Summary dict with keys ``adapter``, ``date``, ``requested``,
        ``written``, ``skipped``.
    """
    dsn = _ingest_dsn()
    instruments = await _load_active_instruments(dsn)
    requested = len(instruments)

    log.info("ingest_prices_start", date=str(target_date), instruments=requested)

    adapter = YFinanceAdapter()
    bars = []
    async for bar in adapter.fetch_daily(instruments, target_date):
        bars.append(bar)

    writer = PostgresWriter(dsn)
    written = await writer.write_prices_daily(bars)
    skipped = requested - len({b.instrument_id for b in bars})

    result: dict[str, Any] = {
        "adapter": adapter.name,
        "date": str(target_date),
        "requested": requested,
        "written": written,
        "skipped": skipped,
    }
    log.info("ingest_prices_done", **result)
    return result


async def ingest_macro(
    target_date: date,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Fetch macro indicator observations and persist them.

    Loads series codes from ``config/fred_series.yaml`` and fetches
    ``lookback_days`` of history up to ``target_date`` to catch any
    late-arriving revisions.

    Args:
        target_date: End of the fetch window (inclusive).
        lookback_days: Number of calendar days to look back.

    Returns:
        Summary dict with keys ``adapter``, ``series``, ``points_written``.
    """
    dsn = _ingest_dsn()

    config = yaml.safe_load((_CONFIG_DIR / "fred_series.yaml").read_text())
    series_codes: list[str] = [entry["code"] for entry in config["series"]]

    start = target_date - timedelta(days=lookback_days)
    log.info(
        "ingest_macro_start",
        series=len(series_codes),
        start=str(start),
        end=str(target_date),
    )

    adapter = FREDAdapter()
    points = []
    async for pt in adapter.fetch(series_codes, start, target_date):
        points.append(pt)

    writer = PostgresWriter(dsn)
    written = await writer.write_macro(points)

    result: dict[str, Any] = {
        "adapter": adapter.name,
        "series": len(series_codes),
        "points_written": written,
    }
    log.info("ingest_macro_done", **result)
    return result


async def backfill_prices(start: date, end: date) -> dict[str, Any]:
    """Backfill daily OHLCV prices for all active instruments over a date range.

    Issues one yfinance ``history()`` call per instrument (not one per day),
    then bulk-loads the results into ``theeyebeta.prices_daily`` with
    ``ON CONFLICT DO NOTHING`` for idempotency.

    Args:
        start: First date of the backfill window (inclusive).
        end: Last date of the backfill window (inclusive).

    Returns:
        Summary dict with keys ``adapter``, ``start``, ``end``,
        ``requested``, ``written``.
    """
    dsn = _ingest_dsn()
    instruments = await _load_active_instruments(dsn)
    requested = len(instruments)

    log.info(
        "backfill_prices_start",
        start=str(start),
        end=str(end),
        instruments=requested,
    )

    adapter = YFinanceAdapter()
    bars: list[Any] = []
    async for bar in adapter.fetch_daily_range(instruments, start, end):
        bars.append(bar)

    writer = PostgresWriter(dsn)
    written = await writer.write_prices_daily(bars)

    result: dict[str, Any] = {
        "adapter": adapter.name,
        "start": str(start),
        "end": str(end),
        "requested": requested,
        "written": written,
    }
    log.info("backfill_prices_done", **result)
    return result


async def backfill_macro(start: date, end: date) -> dict[str, Any]:
    """Backfill macro indicator observations over a date range.

    Fetches all 11 FRED series for the full ``[start, end]`` window in a single
    pass per series.  ON CONFLICT DO NOTHING makes re-runs safe.

    Args:
        start: First date of the backfill window (inclusive).
        end: Last date of the backfill window (inclusive).

    Returns:
        Summary dict with keys ``adapter``, ``start``, ``end``,
        ``series``, ``points_written``.
    """
    dsn = _ingest_dsn()

    config = yaml.safe_load((_CONFIG_DIR / "fred_series.yaml").read_text())
    series_codes: list[str] = [entry["code"] for entry in config["series"]]

    log.info(
        "backfill_macro_start",
        series=len(series_codes),
        start=str(start),
        end=str(end),
    )

    adapter = FREDAdapter()
    points: list[Any] = []
    async for pt in adapter.fetch(series_codes, start, end):
        points.append(pt)

    writer = PostgresWriter(dsn)
    written = await writer.write_macro(points)

    result: dict[str, Any] = {
        "adapter": adapter.name,
        "start": str(start),
        "end": str(end),
        "series": len(series_codes),
        "points_written": written,
    }
    log.info("backfill_macro_done", **result)
    return result
