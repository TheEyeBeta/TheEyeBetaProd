"""Unit tests for IngestionPipeline orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from data_ingestion.pipeline import IngestionPipeline
from data_ingestion.writers.parquet_writer import SnapshotWriteResult
from zinc_schemas.ingestion import PriceDailyRecord


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_run_persists_and_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    target = date(2025, 1, 15)
    observed = datetime(2025, 1, 15, tzinfo=UTC)
    records = [
        PriceDailyRecord(
            source="yfinance",
            observed_at=observed,
            instrument_id=1,
            symbol="AAPL",
            exchange_code="XNAS",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            adj_close=1.5,
            volume=100,
        ),
    ]

    async def fake_fetch(_name: str, _date: date) -> list:
        return records if _name == "yfinance" else []

    mock_conn = AsyncMock()
    mock_conn.transaction = MagicMock()
    mock_conn.transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_writer = AsyncMock()
    mock_writer.write_records.return_value = {"prices_daily": 1}
    row = {
        "symbol": "AAPL",
        "exchange_code": "XNAS",
        "ts": target,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "adj_close": 1.5,
        "volume": 100,
        "source": "yfinance",
    }

    async def fake_market_frame(market: str, _trade_date: date) -> list:
        return [row] if market == "US" else []

    mock_writer.fetch_market_daily_frame.side_effect = fake_market_frame
    mock_writer.register_snapshot.return_value = "00000000-0000-0000-0000-000000000001"

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_parquet = AsyncMock()
    mock_parquet.write_daily_snapshot.return_value = SnapshotWriteResult(
        market="US",
        trade_date=target,
        blob_uri="s3://theeyebeta-snapshots/US/2025/01/2025-01-15.parquet",
        sha256_hex="abc",
        row_count=1,
    )

    mock_js = AsyncMock()
    mock_nc = MagicMock()
    mock_nc.jetstream.return_value = mock_js
    mock_nc.close = AsyncMock()
    monkeypatch.setenv("NATS_URL", "nats://127.0.0.1:4222")

    with (
        patch("data_ingestion.pipeline.get_pool", AsyncMock(return_value=mock_pool)),
        patch("data_ingestion.pipeline.PostgresWriter", return_value=mock_writer),
        patch("data_ingestion.pipeline._fetch_adapter_records", side_effect=fake_fetch),
        patch("data_ingestion.pipeline.nats.connect", AsyncMock(return_value=mock_nc)),
    ):
        pipeline = IngestionPipeline(parquet_writer=mock_parquet)
        summary = await pipeline.run(target, adapter_names=["yfinance"])

    assert summary["written"]["prices_daily"] == 1
    assert "US" in summary["snapshots"]
    mock_js.publish.assert_awaited_once()
    assert summary["nats_events"] == ["data.snapshots.US.2025-01-15"]
    mock_parquet.write_daily_snapshot.assert_called_once()
    market_arg, _, frame_arg = mock_parquet.write_daily_snapshot.call_args[0]
    assert market_arg == "US"
    assert frame_arg.height == 1
