"""FRED adapter: fetches macroeconomic time-series from the St. Louis FRED API."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

import structlog

log = structlog.get_logger()

try:
    from fredapi import Fred as _Fred  # type: ignore[import-untyped]
except ImportError as exc:  # pragma: no cover
    raise ImportError("fredapi is required: uv add fredapi") from exc

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover
    raise ImportError("pandas is required (installed with yfinance)") from exc


from data_ingestion.adapters.base import MacroPoint


class FREDAdapter:
    """Fetches macroeconomic observations from the FRED REST API.

    Implements the MacroAdapter protocol.  Requires the ``FRED_API_KEY``
    environment variable to be set.
    """

    name: str = "fred"

    def __init__(self) -> None:
        """Initialise the FRED client using the FRED_API_KEY env var."""
        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            raise EnvironmentError("FRED_API_KEY environment variable is not set")
        self._fred: Any = _Fred(api_key=api_key)

    async def fetch(
        self,
        series: list[str],
        start: date,
        end: date,
    ) -> AsyncIterator[MacroPoint]:
        """Yield MacroPoint observations for each series in [start, end].

        Fetches are synchronous (fredapi has no async support); they run on the
        calling thread.  For large batch fetches, call from a thread pool.

        Args:
            series: List of FRED series codes (e.g. ``["GDP", "UNRATE"]``).
            start: First date (inclusive).
            end: Last date (inclusive).

        Yields:
            MacroPoint for every non-NaN observation across all series.
        """
        for code in series:
            try:
                raw = self._fred.get_series(
                    code,
                    observation_start=start.isoformat(),
                    observation_end=end.isoformat(),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("fred_fetch_failed", series_code=code, error=str(exc))
                continue

            if raw is None or (hasattr(raw, "empty") and raw.empty):
                log.warning("fred_empty_response", series_code=code)
                continue

            for idx, value in raw.items():
                if pd.isna(value):
                    continue
                # FRED returns timezone-naive Timestamps — treat as UTC.
                if hasattr(idx, "to_pydatetime"):
                    raw_ts: datetime = idx.to_pydatetime()
                    if raw_ts.tzinfo is None:
                        raw_ts = raw_ts.replace(tzinfo=timezone.utc)
                else:
                    raw_ts = datetime(
                        int(idx.year), int(idx.month), int(idx.day),
                        tzinfo=timezone.utc,
                    )
                yield MacroPoint(
                    series_code=code,
                    ts=raw_ts,
                    value=float(value),
                    source="fred",
                )
