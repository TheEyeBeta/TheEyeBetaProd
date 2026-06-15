"""Unit tests for packaged snapshot builder (mocked DB + zinc_native)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from snapshot_packager.builder import SnapshotBuilder

from zinc_schemas.packaged_snapshot import PackagedSnapshotV1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_returns_v1_schema() -> None:
    """SnapshotBuilder.build returns a PackagedSnapshotV1-compatible dict."""
    trade_date = date(2025, 1, 15)
    universe_row = {
        "id": 1,
        "symbol": "AAPL",
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }
    bar_row = {
        "instrument_id": 1,
        "ts": datetime(2025, 1, 15, tzinfo=UTC),
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "adj_close": 105.0,
        "volume": 1_000_000,
    }
    macro_row = {"series_code": "DGS10", "value": 4.25}
    news_row = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "headline": "Test headline",
        "tickers": ["AAPL"],
        "published_at": datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
    }

    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [universe_row],
            [bar_row],
            [macro_row],
            [news_row],
        ],
    )
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    tech = SimpleNamespace(
        atr14=1.5,
        adx14=22.0,
        rsi14=55.0,
        zscore20=0.1,
        bb_upper20_2=110.0,
        bb_lower20_2=90.0,
    )

    with patch(
        "snapshot_packager.builder.snapshot_technicals_last",
        return_value=[tech],
    ):
        payload = await SnapshotBuilder(pool).build("US", trade_date)

    snapshot = PackagedSnapshotV1.model_validate(payload)
    assert snapshot.schema_version == 1
    assert snapshot.market == "US"
    assert snapshot.prices["AAPL"].close == 105.0
    assert snapshot.technicals["AAPL"].rsi14 == 55.0
    assert snapshot.macro["us.dgs10"] == 4.25
    assert len(snapshot.news_summary) == 1
