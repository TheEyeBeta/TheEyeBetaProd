"""yfinance adapter: fetches daily OHLCV bars for equity instruments."""

from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator

import structlog
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from data_ingestion.adapters.base import PriceBar

log = structlog.get_logger()

# Maps MIC exchange code → yfinance ticker suffix.
# Symbols on XNAS / XNYS need no suffix.
_EXCHANGE_SUFFIX: dict[str, str] = {
    "XNAS": "",
    "XNYS": "",
    "XTKS": ".T",
    "XHKG": ".HK",
    "XTAI": ".TW",
    "XSHG": ".SS",
    "XSHE": ".SZ",
}

# yfinance caps concurrent connections; keep parallel fetches low.
_SEMAPHORE_LIMIT = 4


def _make_ticker(symbol: str, exchange_code: str) -> str:
    """Build the yfinance ticker string for a given symbol and exchange.

    Hong Kong symbols are zero-padded to 4 digits (e.g. "700" → "0700.HK").

    Args:
        symbol: Raw symbol string from theeyebeta.instruments.
        exchange_code: MIC exchange code (e.g. "XHKG").

    Returns:
        Fully-qualified yfinance ticker string.
    """
    suffix = _EXCHANGE_SUFFIX.get(exchange_code, "")
    if exchange_code == "XHKG":
        symbol = symbol.zfill(4)
    return f"{symbol}{suffix}"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _fetch_sync(
    ticker_sym: str,
    instrument_id: int,
    target_date: date,
) -> list[PriceBar]:
    """Fetch one day of OHLCV data from yfinance (synchronous).

    Uses ``auto_adjust=False`` to keep the original Close alongside Adj Close.

    Args:
        ticker_sym: yfinance ticker string (e.g. "AAPL", "7203.T").
        instrument_id: PK from theeyebeta.instruments.
        target_date: The trading date to fetch.

    Returns:
        List of PriceBar objects (empty if the ticker had no data that day).
    """
    end_date = target_date + timedelta(days=1)
    ticker = yf.Ticker(ticker_sym)
    hist = ticker.history(
        start=target_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=False,
        prepost=False,
    )
    if hist.empty:
        log.warning(
            "yfinance_empty_response",
            ticker=ticker_sym,
            date=str(target_date),
        )
        return []

    bars: list[PriceBar] = []
    ts = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    for _, row in hist.iterrows():
        bars.append(
            PriceBar(
                instrument_id=instrument_id,
                ts=ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                adj_close=_adj_close(row),
                volume=int(row["Volume"]),
                source="yfinance",
            )
        )
    return bars


def _adj_close(row: Any) -> float | None:
    """Extract the Adj Close value from a yfinance history row, or None if absent/NaN.

    Args:
        row: A pandas Series row from ``Ticker.history()``.

    Returns:
        Adjusted close price, or None if the column is missing or NaN.
    """
    if "Adj Close" not in row.index:
        return None
    try:
        val = float(row["Adj Close"])
        return None if math.isnan(val) else val
    except (TypeError, ValueError):
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _fetch_sync_range(
    ticker_sym: str,
    instrument_id: int,
    start: date,
    end: date,
) -> list[PriceBar]:
    """Fetch a date range of OHLCV data from yfinance (synchronous).

    Issues a single ``history()`` call covering ``[start, end]`` — one network
    round-trip per ticker regardless of how many trading days are in the range.

    Args:
        ticker_sym: yfinance ticker string (e.g. "AAPL", "7203.T").
        instrument_id: PK from theeyebeta.instruments.
        start: First date (inclusive).
        end: Last date (inclusive); yfinance ``end`` is exclusive so +1 day
            is added internally.

    Returns:
        List of PriceBar objects, one per trading day with data.
    """
    end_excl = end + timedelta(days=1)
    ticker = yf.Ticker(ticker_sym)
    hist = ticker.history(
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

    bars: list[PriceBar] = []
    for idx, row in hist.iterrows():
        # idx is a pandas Timestamp; extract the calendar date in UTC.
        if hasattr(idx, "date"):
            bar_date: date = idx.date()
        else:
            bar_date = date(int(idx.year), int(idx.month), int(idx.day))
        ts = datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=timezone.utc)
        bars.append(
            PriceBar(
                instrument_id=instrument_id,
                ts=ts,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                adj_close=_adj_close(row),
                volume=int(row["Volume"]),
                source="yfinance",
            )
        )
    return bars


class YFinanceAdapter:
    """Fetches daily OHLCV bars from Yahoo Finance via the yfinance library.

    Implements the PriceAdapter protocol.  Concurrent fetches are limited to
    ``_SEMAPHORE_LIMIT`` to avoid triggering Yahoo's rate limiter.
    """

    name: str = "yfinance"

    async def fetch_daily(
        self,
        instruments: list[dict[str, Any]],
        target_date: date,
    ) -> AsyncIterator[PriceBar]:
        """Yield PriceBar objects for every instrument on target_date.

        Args:
            instruments: Dicts with keys ``instrument_id``, ``symbol``,
                ``exchange_code``.
            target_date: The calendar date to fetch prices for.

        Yields:
            PriceBar for each instrument that had data.
        """
        sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        loop = asyncio.get_running_loop()

        async def _one(inst: dict[str, Any]) -> list[PriceBar]:
            ticker_sym = _make_ticker(str(inst["symbol"]), str(inst["exchange_code"]))
            async with sem:
                try:
                    return await loop.run_in_executor(
                        None,
                        _fetch_sync,
                        ticker_sym,
                        int(inst["instrument_id"]),
                        target_date,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "yfinance_fetch_failed",
                        ticker=ticker_sym,
                        error=str(exc),
                    )
                    return []

        results = await asyncio.gather(*[_one(inst) for inst in instruments])
        for bars in results:
            for bar in bars:
                yield bar

    async def fetch_daily_range(
        self,
        instruments: list[dict[str, Any]],
        start: date,
        end: date,
    ) -> AsyncIterator[PriceBar]:
        """Yield PriceBar objects for every instrument across a date range.

        Issues a single ``history()`` call per ticker covering ``[start, end]``
        — far fewer API round-trips than calling ``fetch_daily`` once per day.

        Args:
            instruments: Dicts with keys ``instrument_id``, ``symbol``,
                ``exchange_code``.
            start: First date of the range (inclusive).
            end: Last date of the range (inclusive).

        Yields:
            PriceBar for each (instrument, trading-day) pair with data.
        """
        sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
        loop = asyncio.get_running_loop()

        async def _one(inst: dict[str, Any]) -> list[PriceBar]:
            ticker_sym = _make_ticker(str(inst["symbol"]), str(inst["exchange_code"]))
            async with sem:
                try:
                    return await loop.run_in_executor(
                        None,
                        _fetch_sync_range,
                        ticker_sym,
                        int(inst["instrument_id"]),
                        start,
                        end,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "yfinance_range_failed",
                        ticker=ticker_sym,
                        error=str(exc),
                    )
                    return []

        results = await asyncio.gather(*[_one(inst) for inst in instruments])
        for bars in results:
            for bar in bars:
                yield bar
