"""FRED macro series via the public REST API (httpx + VCR-friendly)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import httpx
import structlog
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential
from zinc_schemas.ingestion import MacroRecord, Record

from data_ingestion.adapters.base import _CONFIG_DIR, make_http_client

log = structlog.get_logger()

_FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _fetch_series_observations(
    client: httpx.AsyncClient,
    *,
    series_code: str,
    api_key: str,
    start: date,
    end: date,
) -> list[MacroRecord]:
    params = {
        "series_id": series_code,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
    response = await client.get(_FRED_OBS_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    observations = payload.get("observations", [])
    records: list[MacroRecord] = []
    for obs in observations:
        value_raw = obs.get("value")
        if value_raw in (None, ".", ""):
            continue
        try:
            value = float(value_raw)
        except ValueError:
            continue
        obs_date = date.fromisoformat(str(obs["date"]))
        ts = datetime(obs_date.year, obs_date.month, obs_date.day, tzinfo=UTC)
        records.append(
            MacroRecord(
                source="fred",
                observed_at=ts,
                series_code=series_code,
                value=value,
            )
        )
    return records


def _load_series_codes() -> list[str]:
    config = yaml.safe_load((_CONFIG_DIR / "fred_series.yaml").read_text(encoding="utf-8"))
    return [str(entry["code"]) for entry in config["series"]]


class FredAdapter:
    """Macro observations from FRED (fredapi-compatible series codes)."""

    name = "fred"

    def __init__(self, *, series_codes: list[str] | None = None, lookback_days: int = 30) -> None:
        self._series_codes = series_codes or _load_series_codes()
        self._lookback_days = lookback_days

    async def fetch(
        self,
        target_date: date,
        *,
        start: date | None = None,
    ) -> AsyncIterator[Record]:
        """Yield macro points from FRED for each configured series."""
        api_key = os.environ.get("FRED_API_KEY", "")
        if not api_key:
            raise OSError("FRED_API_KEY environment variable is not set")

        if start is not None:
            window_start = start
        else:
            window_start = target_date - timedelta(days=self._lookback_days)
        async with make_http_client() as client:
            for code in self._series_codes:
                try:
                    points = await _fetch_series_observations(
                        client,
                        series_code=code,
                        api_key=api_key,
                        start=window_start,
                        end=target_date,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("fred_fetch_failed", series_code=code, error=str(exc))
                    continue
                if not points:
                    log.warning("fred_empty_response", series_code=code)
                for point in points:
                    yield point
