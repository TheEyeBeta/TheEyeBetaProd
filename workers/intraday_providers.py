"""Massive 15-minute intraday helpers with parallel batch fetch."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from workers.massive_providers import MASSIVE_BASE_URL, symbol_aliases

log = structlog.get_logger()

DEFAULT_INTRADAY_CONCURRENCY = int(os.environ.get("INTRADAY_FETCH_CONCURRENCY", "80"))
FETCH_RETRIES = 2
FETCH_RETRY_DELAY_SECONDS = 0.5


@dataclass(slots=True, frozen=True)
class IntradayBar:
    """Normalized 15-minute OHLCV bar."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def validate_intraday_bar(row: dict[str, Any]) -> bool:
    """Reject invalid OHLC rows."""
    try:
        open_, high, low, close = (
            float(row["o"]),
            float(row["h"]),
            float(row["l"]),
            float(row["c"]),
        )
    except (KeyError, TypeError, ValueError):
        return False
    return not (high < low or min(open_, high, low, close) <= 0)


def parse_bucket_bar(payload: dict[str, Any], *, bucket_ms: int) -> dict[str, Any] | None:
    """Return the aggregate row matching ``bucket_ms`` from a per-ticker response."""
    for result in payload.get("results") or []:
        if int(result.get("t", 0)) == bucket_ms:
            return result
    return None


class MassiveIntradayClient:
    """Parallel Massive 15-minute bar client (unlimited-plan batch fetch)."""

    def __init__(self, api_key: str | None = None, base_url: str = MASSIVE_BASE_URL) -> None:
        key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not key:
            msg = "MASSIVE_API_KEY is not set"
            raise OSError(msg)
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(45.0, connect=10.0),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def fetch_symbol_bucket(
        self,
        symbol: str,
        bucket: datetime,
    ) -> dict[str, Any] | None:
        """Fetch one 15m bar for ``symbol`` at ``bucket`` (tries symbol aliases)."""
        day = bucket.astimezone(UTC).date().isoformat()
        bucket_ms = int(bucket.astimezone(UTC).timestamp() * 1000)
        for candidate in symbol_aliases(symbol):
            path = f"/v2/aggs/ticker/{candidate}/range/15/minute/{day}/{day}"
            for attempt in range(FETCH_RETRIES + 1):
                try:
                    resp = await self._client.get(
                        path,
                        params={"adjusted": "true", "sort": "asc", "limit": 50000},
                    )
                except httpx.HTTPError as exc:
                    if attempt < FETCH_RETRIES:
                        await asyncio.sleep(FETCH_RETRY_DELAY_SECONDS * (attempt + 1))
                        continue
                    log.warning(
                        "intraday_symbol_fetch_failed",
                        symbol=symbol,
                        candidate=candidate,
                        error=str(exc),
                    )
                    break
                if resp.status_code in {400, 404}:
                    break
                if resp.status_code != 200:
                    if attempt < FETCH_RETRIES:
                        await asyncio.sleep(FETCH_RETRY_DELAY_SECONDS * (attempt + 1))
                        continue
                    break
                row = parse_bucket_bar(resp.json(), bucket_ms=bucket_ms)
                if row is not None:
                    return row
                break
        return None

    async def fetch_symbol_minute_window(
        self,
        symbol: str,
        bucket: datetime,
    ) -> dict[str, Any] | None:
        """Aggregate 1-minute bars in the 15-minute window into one OHLCV bar."""
        start = bucket.astimezone(UTC)
        end = start + timedelta(minutes=15)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        day = start.date().isoformat()
        for candidate in symbol_aliases(symbol):
            path = f"/v2/aggs/ticker/{candidate}/range/1/minute/{day}/{day}"
            try:
                resp = await self._client.get(
                    path,
                    params={"adjusted": "true", "sort": "asc", "limit": 50000},
                )
            except httpx.HTTPError:
                continue
            if resp.status_code != 200:
                continue
            rows = [
                row
                for row in resp.json().get("results") or []
                if start_ms <= int(row.get("t", 0)) < end_ms
            ]
            if not rows:
                continue
            return {
                "o": rows[0]["o"],
                "h": max(float(r["h"]) for r in rows),
                "l": min(float(r["l"]) for r in rows),
                "c": rows[-1]["c"],
                "v": sum(int(r.get("v") or 0) for r in rows),
            }
        return None

    async def fetch_bucket_batch(
        self,
        symbols: list[str],
        bucket: datetime,
        *,
        concurrency: int = DEFAULT_INTRADAY_CONCURRENCY,
    ) -> dict[str, IntradayBar]:
        """Fetch 15m bars for many symbols in parallel (one logical batch per cycle)."""
        semaphore = asyncio.Semaphore(max(1, concurrency))
        bars: dict[str, IntradayBar] = {}

        async def _fetch_one(symbol: str) -> None:
            async with semaphore:
                raw = await self.fetch_symbol_bucket(symbol, bucket)
            if raw is None or not validate_intraday_bar(raw):
                async with semaphore:
                    raw = await self.fetch_symbol_minute_window(symbol, bucket)
            if raw is None or not validate_intraday_bar(raw):
                return
            bars[symbol.upper()] = IntradayBar(
                symbol=symbol.upper(),
                open=float(raw["o"]),
                high=float(raw["h"]),
                low=float(raw["l"]),
                close=float(raw["c"]),
                volume=int(raw.get("v") or 0),
            )

        await asyncio.gather(*(_fetch_one(symbol) for symbol in symbols))
        return bars
