"""Provider clients and pure helpers for MassiveDailyIngestionWorker."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx
import structlog

log = structlog.get_logger()

MASSIVE_BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
LIQUID_SPOT_CHECK_SYMBOLS = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA")
MAX_SINGLE_DAY_MOVE = 0.25
SPOT_CHECK_TOLERANCE = 0.005
COVERAGE_FAIL_THRESHOLD = 0.95
COVERAGE_WARN_THRESHOLD = 0.98
FINNHUB_FALLBACK_MAX = int(os.environ.get("FINNHUB_FALLBACK_MAX", "200"))
FINNHUB_TIMEOUT_SECONDS = float(os.environ.get("FINNHUB_TIMEOUT_SECONDS", "45.0"))
YFINANCE_FALLBACK_MAX = int(os.environ.get("YFINANCE_FALLBACK_MAX", "200"))

CoverageOutcome = Literal["ok", "warn", "fail"]


@dataclass(slots=True, frozen=True)
class UniverseInstrument:
    """Active mapped instrument in the ingestion universe."""

    instrument_id: int
    ticker_id: int
    symbol: str
    exchange_code: str


@dataclass(slots=True)
class DailyBar:
    """Normalized daily OHLCV bar with provenance."""

    instrument_id: int
    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    source: str


def classify_coverage(written: int, expected: int) -> CoverageOutcome:
    """Classify coverage against warn (98%) and fail (95%) gates."""
    if expected <= 0:
        return "fail"
    ratio = written / expected
    if ratio < COVERAGE_FAIL_THRESHOLD:
        return "fail"
    if ratio < COVERAGE_WARN_THRESHOLD:
        return "warn"
    return "ok"


def pick_spot_check_symbols(
    massive_symbols: set[str],
    *,
    liquid: tuple[str, ...] = LIQUID_SPOT_CHECK_SYMBOLS,
    limit: int = 5,
) -> list[str]:
    """Pick liquid symbols present in the Massive batch for cross-provider checks."""
    picked = [symbol for symbol in liquid if symbol in massive_symbols]
    if len(picked) >= limit:
        return picked[:limit]
    for symbol in sorted(massive_symbols):
        if symbol not in picked:
            picked.append(symbol)
        if len(picked) >= limit:
            break
    return picked[:limit]


def validate_bar(
    *,
    symbol: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int,
    prev_close: float | None,
    has_corporate_action: bool,
) -> str | None:
    """Return a rejection reason when the bar fails sanity gates."""
    if high < low:
        return f"{symbol}: high < low"
    for label, value in ("open", open_), ("high", high), ("low", low), ("close", close):
        if value <= 0:
            return f"{symbol}: non-positive {label}={value}"
    if volume < 0:
        return f"{symbol}: negative volume"
    if prev_close and prev_close > 0 and not has_corporate_action:
        move = abs(close / prev_close - 1.0)
        if move > MAX_SINGLE_DAY_MOVE:
            return f"{symbol}: |close/prev-1|={move:.1%} exceeds 25%"
    return None


def symbol_aliases(symbol: str) -> list[str]:
    """Return Massive ↔ DB ticker spelling variants for class shares."""
    sym = symbol.upper()
    aliases = [sym]
    if "-" in sym:
        aliases.append(sym.replace("-", "."))
    if "." in sym:
        aliases.append(sym.replace(".", "-"))
    return list(dict.fromkeys(aliases))


def expanded_symbol_lookup(
    symbol_map: dict[str, UniverseInstrument],
) -> dict[str, UniverseInstrument]:
    """Map Massive ticker spellings to canonical universe instruments."""
    lookup: dict[str, UniverseInstrument] = {}
    for symbol, inst in symbol_map.items():
        for alias in symbol_aliases(symbol):
            lookup.setdefault(alias, inst)
    return lookup


def parse_massive_grouped(
    payload: dict[str, Any],
    *,
    symbol_map: dict[str, UniverseInstrument],
    trade_date: date,
) -> dict[str, DailyBar]:
    """Parse Massive grouped-daily response into symbol → bar."""
    lookup = expanded_symbol_lookup(symbol_map)
    bars: dict[str, DailyBar] = {}
    for row in payload.get("results") or []:
        raw_symbol = str(row.get("T") or row.get("ticker") or "").upper()
        inst = lookup.get(raw_symbol)
        if inst is None:
            continue
        canonical = inst.symbol.upper()
        if canonical in bars:
            continue
        try:
            close = float(row["c"])
            bars[canonical] = DailyBar(
                instrument_id=inst.instrument_id,
                symbol=canonical,
                trade_date=trade_date,
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=close,
                adj_close=float(row.get("vw") or close),
                volume=int(row["v"]),
                source="massive",
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("massive_row_rejected", symbol=raw_symbol, error=str(exc))
    return bars


def provider_chain_plan(
    universe: list[UniverseInstrument],
    massive_bars: dict[str, DailyBar],
) -> list[tuple[UniverseInstrument, Literal["massive", "finnhub", "yfinance"]]]:
    """Return per-instrument provider order for a run (massive first, then fallbacks)."""
    plan: list[tuple[UniverseInstrument, Literal["massive", "finnhub", "yfinance"]]] = []
    for inst in universe:
        if inst.symbol in massive_bars:
            plan.append((inst, "massive"))
        else:
            plan.append((inst, "finnhub"))
    return plan


def bars_still_missing(
    universe: list[UniverseInstrument],
    collected: dict[str, DailyBar],
) -> list[UniverseInstrument]:
    """Return universe instruments without a collected bar."""
    return [inst for inst in universe if inst.symbol not in collected]


class MassiveClient:
    """Polygon-compatible Massive.com grouped-daily client."""

    def __init__(self, api_key: str | None = None, base_url: str = MASSIVE_BASE_URL) -> None:
        key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not key:
            msg = "MASSIVE_API_KEY is not set"
            raise OSError(msg)
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def grouped_daily(self, trade_date: date) -> dict[str, Any]:
        """Fetch grouped daily aggregates for a US equities session date."""
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{trade_date.isoformat()}"
        response = await self._client.get(
            f"{self.base_url}{path}",
            params={"adjusted": "true", "include_otc": "false", "apiKey": self.api_key},
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") == "NOT_FOUND":
            return {}
        return payload


class FinnhubClient:
    """Finnhub daily candle fallback client."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("FINNHUB_API_KEY")
        if not key:
            msg = "FINNHUB_API_KEY is not set"
            raise OSError(msg)
        self.api_key = key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(FINNHUB_TIMEOUT_SECONDS, connect=10.0),
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def daily_bar(self, symbol: str, trade_date: date) -> DailyBar | None:
        """Fetch one daily OHLCV bar for ``symbol`` on ``trade_date``."""
        start = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=UTC)
        end = start + timedelta(days=1)
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
            "token": self.api_key,
        }
        async with self._lock:
            now = asyncio.get_running_loop().time()
            wait = 1.1 - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self._client.get(
                    f"{FINNHUB_BASE_URL}/stock/candle",
                    params=params,
                )
            except httpx.HTTPError as exc:
                log.warning("finnhub_request_failed", symbol=symbol, error=str(exc))
                return None
            self._last_request = asyncio.get_running_loop().time()

        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("s") != "ok":
            return None
        closes = data.get("c") or []
        if not closes:
            return None
        idx = -1
        close = float(closes[idx])
        return DailyBar(
            instrument_id=0,
            symbol=symbol,
            trade_date=trade_date,
            open=float((data.get("o") or [0])[idx]),
            high=float((data.get("h") or [0])[idx]),
            low=float((data.get("l") or [0])[idx]),
            close=close,
            adj_close=close,
            volume=int((data.get("v") or [0])[idx]),
            source="finnhub",
        )


def _ensure_yfinance_path() -> None:
    di_src = Path(__file__).resolve().parents[1] / "services" / "data_ingestion" / "src"
    text = str(di_src)
    if text not in sys.path:
        sys.path.insert(0, text)


def fetch_yfinance_bar(inst: UniverseInstrument, trade_date: date) -> DailyBar | None:
    """Fetch a single daily bar via yfinance (sync; run in executor)."""
    _ensure_yfinance_path()
    from data_ingestion.adapters.yfinance import _fetch_sync, make_ticker

    ticker = make_ticker(inst.symbol, inst.exchange_code)
    records = _fetch_sync(
        ticker,
        inst.instrument_id,
        inst.symbol,
        inst.exchange_code,
        trade_date,
    )
    if not records:
        return None
    record = records[0]
    close = float(record.close)
    return DailyBar(
        instrument_id=inst.instrument_id,
        symbol=inst.symbol,
        trade_date=trade_date,
        open=float(record.open),
        high=float(record.high),
        low=float(record.low),
        close=close,
        adj_close=float(record.adj_close or close),
        volume=int(record.volume),
        source="yfinance",
    )


def bar_to_row(bar: DailyBar) -> tuple[Any, ...]:
    """Convert a bar to DB bind parameters."""
    ts = datetime(bar.trade_date.year, bar.trade_date.month, bar.trade_date.day, tzinfo=UTC)
    return (
        bar.instrument_id,
        ts,
        Decimal(str(bar.open)),
        Decimal(str(bar.high)),
        Decimal(str(bar.low)),
        Decimal(str(bar.close)),
        Decimal(str(bar.adj_close)),
        bar.volume,
        bar.source,
    )
