"""Small async FRED REST client used by macro workers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import httpx


@dataclass(frozen=True, slots=True)
class FredObservation:
    """One parsed FRED observation."""

    observed_date: date
    value: float

    @property
    def observed_at(self) -> datetime:
        return datetime.combine(self.observed_date, time.min, tzinfo=UTC)


class FredClient:
    """Direct FRED API client. API key is read from ``FRED_API_KEY``."""

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY", "")
        if not self.api_key:
            msg = "FRED_API_KEY is required"
            raise OSError(msg)
        self.timeout = timeout

    async def observations(
        self,
        series_id: str,
        *,
        start: date,
        end: date,
    ) -> list[FredObservation]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
            "sort_order": "asc",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params=params,
            )
            response.raise_for_status()
        payload = response.json()
        observations: list[FredObservation] = []
        for raw in payload.get("observations", []):
            raw_value = raw.get("value")
            if raw_value in (None, "."):
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            observations.append(
                FredObservation(
                    observed_date=date.fromisoformat(raw["date"]),
                    value=value,
                ),
            )
        return observations

    async def latest_value(
        self,
        series_id: str,
        *,
        as_of: date,
        lookback_days: int = 800,
    ) -> FredObservation:
        observations = await self.observations(
            series_id,
            start=as_of - timedelta(days=lookback_days),
            end=as_of,
        )
        if not observations:
            msg = f"No FRED observations for {series_id} on or before {as_of}"
            raise ValueError(msg)
        return observations[-1]
