"""Yahoo Finance daily OHLCV for US / HK / JP / TW universes."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import structlog
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from data_ingestion.adapters.base import (
    _YFINANCE_EXCHANGES,
    load_active_instruments,
    make_http_client,
)
from zinc_schemas.ingestion import PriceDailyRecord, Record

log = structlog.get_logger()

_EXCHANGE_SUFFIX: dict[str, str] = {
    "XNAS": "",
    "XNYS": "",
    "XTKS": ".T",
    "XHKG": ".HK",
    "XTAI": ".TW",
}

_SEMAPHORE_LIMIT = 4
_MIN_REQUEST_INTERVAL = 0.35


def make_ticker(symbol: str, exchange_code: str) -> str:
    """Build a yfinance ticker string (HK symbols zero-padded to 4 digits)."""
    suffix = _EXCHANGE_SUFFIX.get(exchange_code, "")
    if exchange_code == "XHKG":
        symbol = symbol.zfill(4)
    return f"{symbol}{suffix}"


def _adj_close(row: pd.Series) -> float | None:  # type: ignore[type-arg]
    if "Adj Close" not in row.index:
        return None
    try:
        val = float(row["Adj Close"])
        return None if math.isnan(val) else val
    except (TypeError, ValueError):
        return None


def _rows_to_records(
    hist: pd.DataFrame,
    *,
    instrument_id: int,
    symbol: str,
    exchange_code: str,
    target_date: date,
) -> list[PriceDailyRecord]:
    if hist.empty:
        return []
    ts = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
    records: list[PriceDailyRecord] = []
    for _, row in hist.iterrows():
        records.append(
            PriceDailyRecord(
                source="yfinance",
                observed_at=ts,
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                adj_close=_adj_close(row),
                volume=int(row["Volume"]),
            )
        )
    return records


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _fetch_sync(
    ticker_sym: str,
    instrument_id: int,
    symbol: str,
    exchange_code: str,
    target_date: date,
) -> list[PriceDailyRecord]:
    end_date = target_date + timedelta(days=1)
    hist = yf.Ticker(ticker_sym).history(
        start=target_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=False,
        prepost=False,
    )
    if hist.empty:
        log.warning("yfinance_empty_response", ticker=ticker_sym, date=str(target_date))
        return []
    return _rows_to_records(
        hist,
        instrument_id=instrument_id,
        symbol=symbol,
        exchange_code=exchange_code,
        target_date=target_date,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _fetch_sync_range(
    ticker_sym: str,
    instrument_id: int,
    symbol: str,
    exchange_code: str,
    start: date,
    end: date,
) -> list[PriceDailyRecord]:
    end_excl = end + timedelta(days=1)
    hist = yf.Ticker(ticker_sym).history(
        start=start.isoformat(),
        end=end_excl.isoformat(),
        auto_adjust=False,
        prepost=False,
    )
    if hist.empty:
        log.warning(
            "yfinance_empty_range",
            ticker=ticker_sym,
            start=str(start),
            end=str(end),
        )
        return []
    records: list[PriceDailyRecord] = []
    for idx, row in hist.iterrows():
        if hasattr(idx, "date"):
            bar_date: date = idx.date()
        else:
            bar_date = date(int(idx.year), int(idx.month), int(idx.day))
        ts = datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=UTC)
        records.append(
            PriceDailyRecord(
                source="yfinance",
                observed_at=ts,
                instrument_id=instrument_id,
                symbol=symbol,
                exchange_code=exchange_code,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                adj_close=_adj_close(row),
                volume=int(row["Volume"]),
            )
        )
    return records


class YfinanceAdapter:
    """Daily OHLCV via yfinance with conservative concurrency and retries."""

    name = "yfinance"

    def __init__(self, instruments: list[dict[str, Any]] | None = None) -> None:
        self._instruments = instruments

    async def fetch_daily_range(
        self,
        instruments: list[dict[str, Any]],
        start: date,
        end: date,
    ) -> AsyncIterator[PriceDailyRecord]:
        """Yield daily bars across a date range (one yfinance call per ticker)."""
        sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        loop = asyncio.get_running_loop()

        async def _one(inst: dict[str, Any]) -> list[PriceDailyRecord]:
            ticker_sym = make_ticker(str(inst["symbol"]), str(inst["exchange_code"]))
            async with sem:
                try:
                    async with make_http_client():
                        return await loop.run_in_executor(
                            None,
                            _fetch_sync_range,
                            ticker_sym,
                            int(inst["instrument_id"]),
                            str(inst["symbol"]),
                            str(inst["exchange_code"]),
                            start,
                            end,
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("yfinance_range_failed", ticker=ticker_sym, error=str(exc))
                    return []

        results = await asyncio.gather(*[_one(inst) for inst in instruments])
        for batch in results:
            for record in batch:
                yield record

    async def fetch(self, target_date: date) -> AsyncIterator[Record]:
        """Yield daily price records for US/HK/JP/TW instruments."""
        instruments = self._instruments
        if instruments is None:
            all_inst = await load_active_instruments()
            instruments = [i for i in all_inst if str(i["exchange_code"]) in _YFINANCE_EXCHANGES]

        sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        loop = asyncio.get_running_loop()
        throttle = asyncio.Lock()
        last_request = 0.0

        async def _one(inst: dict[str, Any]) -> list[PriceDailyRecord]:
            ticker_sym = make_ticker(str(inst["symbol"]), str(inst["exchange_code"]))
            async with sem:
                nonlocal last_request
                async with throttle:
                    now = loop.time()
                    wait = _MIN_REQUEST_INTERVAL - (now - last_request)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_request = loop.time()
                try:
                    async with make_http_client():
                        return await loop.run_in_executor(
                            None,
                            _fetch_sync,
                            ticker_sym,
                            int(inst["instrument_id"]),
                            str(inst["symbol"]),
                            str(inst["exchange_code"]),
                            target_date,
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("yfinance_fetch_failed", ticker=ticker_sym, error=str(exc))
                    return []

        results = await asyncio.gather(*[_one(inst) for inst in instruments])
        for batch in results:
            for record in batch:
                yield record
