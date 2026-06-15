"""Unit tests for the China proxy adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from data_ingestion.adapters.cn_proxy import CnProxyAdapter

from zinc_schemas.ingestion import PriceDailyRecord


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_uses_adr_fallback_when_primary_empty() -> None:
    target = date(2025, 1, 15)
    instruments = [{"instrument_id": 9, "symbol": "600519", "exchange_code": "XSHG"}]
    primary: list[PriceDailyRecord] = []
    adr = [
        PriceDailyRecord(
            source="yfinance",
            observed_at=datetime(2025, 1, 15, tzinfo=UTC),
            instrument_id=9,
            symbol="600519",
            exchange_code="XSHG",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            adj_close=1.5,
            volume=100,
        )
    ]

    def fake_fetch(ticker: str, *_args: object, **_kwargs: object) -> list[PriceDailyRecord]:
        return adr if ticker == "MOUTF" else primary

    adapter = CnProxyAdapter(
        instruments,
        adr_fallbacks={("600519", "XSHG"): "MOUTF"},
    )
    with patch("data_ingestion.adapters.cn_proxy._fetch_sync", side_effect=fake_fetch):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].source == "cn_proxy"
