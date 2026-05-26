"""Unit tests for the yfinance adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from data_ingestion.adapters.yfinance import YfinanceAdapter, make_ticker
from zinc_schemas.ingestion import PriceDailyRecord


@pytest.mark.unit
def test_make_ticker_hk_zero_pads() -> None:
    assert make_ticker("700", "XHKG") == "0700.HK"


@pytest.mark.unit
def test_make_ticker_tokyo_suffix() -> None:
    assert make_ticker("7203", "XTKS") == "7203.T"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_yields_price_daily_records() -> None:
    target = date(2025, 1, 15)
    sample = [
        PriceDailyRecord(
            source="yfinance",
            observed_at=datetime(2025, 1, 15, tzinfo=UTC),
            instrument_id=1,
            symbol="AAPL",
            exchange_code="XNAS",
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            adj_close=105.0,
            volume=1_000_000,
        )
    ]
    instruments = [{"instrument_id": 1, "symbol": "AAPL", "exchange_code": "XNAS"}]
    adapter = YfinanceAdapter(instruments)

    with patch(
        "data_ingestion.adapters.yfinance._fetch_sync",
        return_value=sample,
    ):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 1
    assert records[0].record_type == "price_daily"
    assert records[0].symbol == "AAPL"
