"""Unit tests for the FRED adapter (VCR-recorded HTTP)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from data_ingestion.adapters.fred import FredAdapter

from .vcr_helpers import cassette_response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_yields_macro_records_from_vcr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    status, body = cassette_response("fred_gdp.yaml")
    target = date(2024, 4, 1)

    async def mock_get(url: str, params: dict[str, str] | None = None) -> httpx.Response:
        assert "GDP" in (params or {}).get("series_id", "")
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    adapter = FredAdapter(series_codes=["GDP"], lookback_days=120)
    with patch("data_ingestion.adapters.fred.make_http_client", return_value=mock_client):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].record_type == "macro"
    assert records[0].series_code == "GDP"
    assert records[0].value == 28624.069
