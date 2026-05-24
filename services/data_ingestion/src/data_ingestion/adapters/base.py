"""Base protocols and data models for data-ingestion adapters."""

from __future__ import annotations

from datetime import date, datetime
from typing import AsyncIterator, Protocol

from pydantic import BaseModel


class PriceBar(BaseModel):
    """One OHLCV bar for a single instrument on a single day."""

    instrument_id: int
    ts: datetime  # timezone-aware UTC midnight
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int
    source: str


class MacroPoint(BaseModel):
    """One observation for a single macro time-series."""

    series_code: str
    ts: datetime  # timezone-aware UTC
    value: float
    source: str


class PriceAdapter(Protocol):
    """Protocol for daily equity price adapters."""

    name: str

    async def fetch_daily(
        self,
        instruments: list[dict[str, object]],
        target_date: date,
    ) -> AsyncIterator[PriceBar]:
        """Yield PriceBar objects for every instrument on target_date.

        Args:
            instruments: List of instrument dicts with keys ``instrument_id``,
                ``symbol``, ``exchange_code``.
            target_date: The calendar date to fetch prices for.

        Yields:
            PriceBar: One bar per instrument that had data on target_date.
        """
        ...  # pragma: no cover


class MacroAdapter(Protocol):
    """Protocol for macroeconomic series adapters."""

    name: str

    async def fetch(
        self,
        series: list[str],
        start: date,
        end: date,
    ) -> AsyncIterator[MacroPoint]:
        """Yield MacroPoint observations for each series in [start, end].

        Args:
            series: List of series codes to fetch.
            start: First date (inclusive).
            end: Last date (inclusive).

        Yields:
            MacroPoint: One point per observation across all series.
        """
        ...  # pragma: no cover
