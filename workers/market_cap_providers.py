"""Massive reference helpers and market-cap threshold logic."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from urllib.parse import quote

import httpx
import structlog

log = structlog.get_logger()

MASSIVE_BASE_URL = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
CAP_THRESHOLD_USD = 500_000_000
DEFAULT_FETCH_CONCURRENCY = 10
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.12

CapEventType = Literal["CROSSED_UP", "CROSSED_DOWN"]

# Map 2-digit SIC major groups → GICS-style sector labels used in theeyebeta.
_SIC_MAJOR_SECTOR: tuple[tuple[int, str], ...] = (
    (9, "Consumer Defensive"),
    (12, "Energy"),
    (14, "Basic Materials"),
    (17, "Industrials"),
    (21, "Consumer Defensive"),
    (25, "Consumer Cyclical"),
    (27, "Basic Materials"),
    (29, "Energy"),
    (34, "Industrials"),
    (36, "Industrials"),
    (37, "Consumer Cyclical"),
    (38, "Healthcare"),
    (39, "Industrials"),
    (41, "Industrials"),
    (47, "Industrials"),
    (48, "Communication Services"),
    (49, "Utilities"),
    (51, "Consumer Cyclical"),
    (59, "Consumer Cyclical"),
    (67, "Financials"),
    (72, "Consumer Cyclical"),
    (79, "Industrials"),
    (87, "Technology"),
    (99, "Industrials"),
)

# Software / semiconductors / electronic computers override broad manufacturing bins.
_SIC_EXACT_SECTOR: dict[int, str] = {
    3571: "Technology",
    3572: "Technology",
    3575: "Technology",
    3577: "Technology",
    3661: "Technology",
    3663: "Technology",
    3669: "Technology",
    3674: "Technology",
    3812: "Technology",
    7370: "Technology",
    7371: "Technology",
    7372: "Technology",
    7373: "Technology",
    7374: "Technology",
    7375: "Technology",
    7376: "Technology",
    7377: "Technology",
    7378: "Technology",
    7379: "Technology",
    4812: "Communication Services",
    4813: "Communication Services",
    4833: "Communication Services",
    4899: "Communication Services",
    2834: "Healthcare",
    2836: "Healthcare",
    3841: "Healthcare",
    3845: "Healthcare",
    6798: "Real Estate",
    6500: "Real Estate",
    6510: "Real Estate",
    6512: "Real Estate",
    6513: "Real Estate",
    6514: "Real Estate",
    6515: "Real Estate",
    6517: "Real Estate",
    6519: "Real Estate",
}

# Massive ticker types without SIC still need a sector bucket for aggregation.
_MASSIVE_TYPE_SECTOR: dict[str, str] = {
    "ETF": "ETF",
    "ETV": "ETF",
    "ETS": "ETF",
    "FUND": "Fund",
    "WARRANT": "Warrant",
    "PFD": "Preferred",
    "UNIT": "Unit",
    "RIGHT": "Right",
}

_MASSIVE_TYPE_ASSET_CLASS: dict[str, str] = {
    "ETF": "etf",
    "ETV": "etf",
    "ETS": "etf",
    "FUND": "etf",
    "ADRC": "adr",
}

# Align yfinance GICS labels with theeyebeta sector_daily naming.
_YFINANCE_SECTOR_NORMALIZE: dict[str, str] = {
    "Financial Services": "Financials",
    "Consumer Cyclicals": "Consumer Cyclical",
    "Consumer Defensives": "Consumer Defensive",
    "Basic Materials": "Basic Materials",
    "Communication Services": "Communication Services",
}


def sector_from_sic_code(sic_code: str | int | None) -> str | None:
    """Map a SIC code to a coarse GICS-style sector label."""
    if sic_code is None:
        return None
    try:
        code = int(str(sic_code).strip())
    except ValueError:
        return None
    if code in _SIC_EXACT_SECTOR:
        return _SIC_EXACT_SECTOR[code]
    major = code // 100
    for limit, sector in _SIC_MAJOR_SECTOR:
        if major <= limit:
            return sector
    return None


def sector_from_massive_detail(detail: dict[str, Any] | None) -> str | None:
    """Derive sector from Massive ``/v3/reference/tickers`` payload."""
    if not detail:
        return None
    sic_sector = sector_from_sic_code(detail.get("sic_code"))
    if sic_sector:
        return sic_sector
    ticker_type = str(detail.get("type") or "").upper()
    type_sector = _MASSIVE_TYPE_SECTOR.get(ticker_type)
    if type_sector:
        return type_sector
    return _sector_from_massive_metadata(detail)


def _sector_from_massive_metadata(detail: dict[str, Any]) -> str | None:
    """Heuristic sector for reference rows without SIC (e.g. misclassified funds)."""
    name = str(detail.get("name") or "").lower()
    description = str(detail.get("description") or "").lower()
    fund_markers = (
        " fund",
        "etf",
        "closed-end",
        "investment company",
        "business development company",
    )
    haystack = f" {name} {description}"
    if any(marker in haystack for marker in fund_markers):
        return "Fund"
    return None


def asset_class_from_massive_detail(detail: dict[str, Any] | None) -> str | None:
    """Map Massive ticker type to theeyebeta.instruments.asset_class when known."""
    if not detail:
        return None
    ticker_type = str(detail.get("type") or "").upper()
    return _MASSIVE_TYPE_ASSET_CLASS.get(ticker_type)


def normalize_yfinance_sector(sector: str | None) -> str | None:
    """Normalize a yfinance sector label to theeyebeta conventions."""
    if sector is None:
        return None
    cleaned = str(sector).strip()
    if not cleaned:
        return None
    return _YFINANCE_SECTOR_NORMALIZE.get(cleaned, cleaned)


def sector_from_yfinance_info(info: dict[str, Any] | None) -> str | None:
    """Extract a GICS-style sector from a yfinance ``Ticker.info`` payload."""
    if not info:
        return None
    return normalize_yfinance_sector(info.get("sector"))


def _fetch_yfinance_sector_sync(symbol: str) -> str | None:
    import yfinance as yf

    for candidate in reference_ticker_variants(symbol):
        ticker = yf.Ticker(candidate)
        info = ticker.info or {}
        sector = sector_from_yfinance_info(info)
        if sector:
            return sector
        fast = getattr(ticker, "fast_info", None)
        if fast is not None:
            raw = getattr(fast, "get", lambda _k, _d=None: None)("sector")
            sector = normalize_yfinance_sector(raw)
            if sector:
                return sector
    return None


async def fetch_yfinance_sectors(
    symbols: list[str],
    *,
    min_interval_seconds: float = 1.0,
) -> dict[str, str]:
    """Return symbol → sector for symbols with a resolvable yfinance profile."""
    sectors: dict[str, str] = {}
    for symbol in symbols:
        try:
            sector = await asyncio.to_thread(_fetch_yfinance_sector_sync, symbol)
            if sector:
                sectors[symbol] = sector
        except Exception as exc:  # noqa: BLE001
            log.warning("yfinance_sector_fetch_failed", symbol=symbol, error=str(exc))
        if min_interval_seconds > 0:
            await asyncio.sleep(min_interval_seconds)
    return sectors


@dataclass(slots=True, frozen=True)
class InstrumentTags:
    """Sector and optional asset_class from a reference provider."""

    sector: str | None
    asset_class: str | None = None


async def fetch_massive_instrument_tags(
    client: MassiveReferenceClient,
    symbols: list[str],
    *,
    concurrency: int = DEFAULT_FETCH_CONCURRENCY,
    min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
) -> dict[str, InstrumentTags]:
    """Return symbol → tags for symbols with SIC, Massive type, or both."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    last_request = 0.0
    tags: dict[str, InstrumentTags] = {}

    async def _fetch_one(symbol: str) -> None:
        nonlocal last_request
        try:
            async with semaphore:
                async with lock:
                    now = asyncio.get_running_loop().time()
                    wait = min_interval_seconds - (now - last_request)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_request = asyncio.get_running_loop().time()
                detail = await client.ticker_detail(symbol)
            sector = sector_from_massive_detail(detail)
            asset_class = asset_class_from_massive_detail(detail)
            if sector or asset_class:
                tags[symbol] = InstrumentTags(sector=sector, asset_class=asset_class)
        except Exception as exc:  # noqa: BLE001
            log.warning("massive_sector_fetch_failed", symbol=symbol, error=str(exc))

    await asyncio.gather(*(_fetch_one(symbol) for symbol in symbols))
    return tags


async def fetch_massive_sectors(
    client: MassiveReferenceClient,
    symbols: list[str],
    *,
    concurrency: int = DEFAULT_FETCH_CONCURRENCY,
    min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
) -> dict[str, str]:
    """Return symbol → sector for symbols with a resolvable Massive reference tag."""
    tag_map = await fetch_massive_instrument_tags(
        client,
        symbols,
        concurrency=concurrency,
        min_interval_seconds=min_interval_seconds,
    )
    return {
        symbol: meta.sector
        for symbol, meta in tag_map.items()
        if meta.sector
    }


@dataclass(slots=True, frozen=True)
class CapSnapshot:
    """One symbol's market-cap observation for a trade date."""

    symbol: str
    market_cap: float
    close_price: float | None = None
    shares_outstanding: int | None = None
    instrument_id: int | None = None


@dataclass(slots=True, frozen=True)
class CapCrossing:
    """A symbol that crossed the configured cap threshold."""

    symbol: str
    event_type: CapEventType
    market_cap: float
    prior_market_cap: float | None
    instrument_id: int | None


def reference_ticker_variants(symbol: str) -> list[str]:
    """Return Massive reference ticker path variants for class-share symbols."""
    sym = symbol.upper()
    variants = [sym]
    if "-" in sym:
        variants.append(sym.replace("-", "."))
    if "." in sym:
        variants.append(sym.replace(".", "-"))
    return list(dict.fromkeys(variants))


def action_for_event(event_type: CapEventType) -> str:
    """Return the ops action label for a crossing event."""
    if event_type == "CROSSED_UP":
        return "ADD_TO_INTRADAY"
    return "REMOVE_FROM_INTRADAY"


def classify_cap_crossings(
    today: dict[str, CapSnapshot],
    yesterday: dict[str, CapSnapshot],
    *,
    threshold: float = CAP_THRESHOLD_USD,
) -> list[CapCrossing]:
    """Detect symbols crossing ``threshold`` between two cap snapshots."""
    crossings: list[CapCrossing] = []
    symbols = set(today) | set(yesterday)
    for symbol in sorted(symbols):
        today_row = today.get(symbol)
        prior_row = yesterday.get(symbol)
        today_cap = today_row.market_cap if today_row else None
        prior_cap = prior_row.market_cap if prior_row else None
        if today_cap is None:
            continue

        instrument_id = today_row.instrument_id if today_row else None
        if prior_cap is None:
            continue

        if prior_cap < threshold <= today_cap:
            crossings.append(
                CapCrossing(
                    symbol=symbol,
                    event_type="CROSSED_UP",
                    market_cap=today_cap,
                    prior_market_cap=prior_cap,
                    instrument_id=instrument_id,
                ),
            )
        elif prior_cap >= threshold > today_cap:
            crossings.append(
                CapCrossing(
                    symbol=symbol,
                    event_type="CROSSED_DOWN",
                    market_cap=today_cap,
                    prior_market_cap=prior_cap,
                    instrument_id=instrument_id,
                ),
            )
    return crossings


def symbols_above_threshold(
    snapshots: dict[str, CapSnapshot],
    *,
    threshold: float = CAP_THRESHOLD_USD,
) -> list[str]:
    """Return sorted symbols at or above ``threshold``."""
    return sorted(symbol for symbol, row in snapshots.items() if row.market_cap >= threshold)


class MassiveReferenceClient:
    """Polygon-compatible Massive reference and grouped-daily client."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = MASSIVE_BASE_URL,
    ) -> None:
        key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not key:
            msg = "MASSIVE_API_KEY is not set"
            raise OSError(msg)
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def grouped_daily(self, trade_date: date) -> dict[str, float]:
        """Return symbol → close for a US grouped-daily session."""
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{trade_date.isoformat()}"
        response = await self._client.get(
            f"{self.base_url}{path}",
            params={"adjusted": "true", "include_otc": "false", "apiKey": self.api_key},
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        closes: dict[str, float] = {}
        for row in payload.get("results") or []:
            symbol = str(row.get("T") or row.get("ticker") or "").upper()
            if not symbol:
                continue
            try:
                closes[symbol] = float(row["c"])
            except (KeyError, TypeError, ValueError):
                continue
        return closes

    async def ticker_detail(self, symbol: str) -> dict[str, Any] | None:
        """Fetch one ticker reference record including ``market_cap``."""
        for candidate in reference_ticker_variants(symbol):
            path = f"/v3/reference/tickers/{quote(candidate, safe='')}"
            response = await self._client.get(
                f"{self.base_url}{path}",
                params={"apiKey": self.api_key},
            )
            if response.status_code in {400, 404}:
                continue
            if response.status_code != 200:
                response.raise_for_status()
            payload = response.json()
            results = payload.get("results")
            if isinstance(results, dict):
                return results
        return None

    async def iter_us_common_stock_symbols(self) -> list[str]:
        """Return active US common-stock symbols from the reference list."""
        symbols: list[str] = []
        url = f"{self.base_url}/v3/reference/tickers"
        params: dict[str, str | int] | None = {
            "market": "stocks",
            "active": "true",
            "limit": 1000,
            "sort": "ticker",
            "apiKey": self.api_key,
        }
        while url:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            for row in payload.get("results") or []:
                if row.get("locale") != "us" or row.get("type") != "CS":
                    continue
                symbol = str(row.get("ticker") or "").upper()
                if symbol:
                    symbols.append(symbol)
            next_url = payload.get("next_url")
            if next_url:
                url = f"{self.base_url}{next_url}" if next_url.startswith("/") else next_url
                params = {"apiKey": self.api_key}
            else:
                url = ""
        return symbols


async def fetch_cap_snapshots(
    client: MassiveReferenceClient,
    symbols: list[str],
    *,
    grouped_closes: dict[str, float],
    instrument_ids: dict[str, int],
    concurrency: int = DEFAULT_FETCH_CONCURRENCY,
    min_interval_seconds: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
) -> list[CapSnapshot]:
    """Fetch cap snapshots for ``symbols`` using Massive reference detail."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    last_request = 0.0
    snapshots: list[CapSnapshot] = []

    async def _fetch_one(symbol: str) -> CapSnapshot | None:
        nonlocal last_request
        try:
            async with semaphore:
                async with lock:
                    now = asyncio.get_running_loop().time()
                    wait = min_interval_seconds - (now - last_request)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_request = asyncio.get_running_loop().time()
                detail = await client.ticker_detail(symbol)
                if detail is None:
                    return None
                market_cap = detail.get("market_cap")
                shares = detail.get("share_class_shares_outstanding")
                close = grouped_closes.get(symbol)
                cap_value: float | None = None
                if market_cap is not None:
                    try:
                        cap_value = float(market_cap)
                    except (TypeError, ValueError):
                        cap_value = None
                if cap_value is None and close is not None and shares is not None:
                    try:
                        cap_value = float(close) * float(shares)
                    except (TypeError, ValueError):
                        cap_value = None
                if cap_value is None or cap_value <= 0:
                    return None
                shares_int: int | None = None
                if shares is not None:
                    try:
                        shares_int = int(shares)
                    except (TypeError, ValueError):
                        shares_int = None
                return CapSnapshot(
                    symbol=symbol,
                    market_cap=cap_value,
                    close_price=close,
                    shares_outstanding=shares_int,
                    instrument_id=instrument_ids.get(symbol),
                )
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not abort the run
            log.warning("market_cap_symbol_fetch_failed", symbol=symbol, error=str(exc))
            return None

    results = await asyncio.gather(*(_fetch_one(symbol) for symbol in symbols))
    for row in results:
        if row is not None:
            snapshots.append(row)
    return snapshots
