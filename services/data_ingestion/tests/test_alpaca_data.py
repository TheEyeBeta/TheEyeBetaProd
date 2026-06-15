"""Unit tests for the Alpaca market-data adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from data_ingestion.adapters.alpaca_data import AlpacaDataAdapter

from zinc_schemas.ingestion import IntradayBarRecord


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_yields_intraday_bars() -> None:
    target = date(2025, 1, 15)
    bar = SimpleNamespace(
        timestamp=datetime(2025, 1, 15, 14, 30, tzinfo=UTC),
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=1000,
    )
    bars_map = SimpleNamespace(data={"AAPL": [bar]})
    instruments = [{"instrument_id": 42, "symbol": "AAPL", "exchange_code": "XNAS"}]
    adapter = AlpacaDataAdapter(instruments)

    mock_client = SimpleNamespace(get_stock_bars=lambda _req: bars_map)
    with patch.object(AlpacaDataAdapter, "_client", return_value=mock_client):
        records = [record async for record in adapter.fetch(target)]

    assert len(records) == 2
    assert all(isinstance(r, IntradayBarRecord) for r in records)
    assert {r.bar_seconds for r in records} == {60, 300}
