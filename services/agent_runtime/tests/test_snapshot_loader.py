"""Unit tests for SnapshotLoader."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from agent_runtime.snapshot_loader import SnapshotLoader

_SNAPSHOT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
_VALID = {
    "schema_version": 1,
    "market": "US",
    "snapshot_id": str(_SNAPSHOT_ID),
    "as_of": "2025-01-15T23:59:59+00:00",
    "universe": [{"symbol": "AAPL", "instrument_id": 1, "sector": "Tech", "industry": None}],
    "prices": {
        "AAPL": {
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "adj_close": 1.5,
            "volume": 100,
        },
    },
    "technicals": {
        "AAPL": {
            "atr14": 1.0,
            "adx14": 20.0,
            "rsi14": 55.0,
            "zscore20": 0.1,
            "bb_upper20_2": 2.0,
            "bb_lower20_2": 1.0,
        },
    },
    "macro": {},
    "news_summary": [],
}


@pytest.mark.unit
async def test_load_cache_hit() -> None:
    """Redis cache short-circuits MinIO fetch."""
    loader = SnapshotLoader(
        database_url="postgresql://u:p@localhost/db",
        redis_url="redis://127.0.0.1:6379/0",
    )
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(_VALID))
    loader._redis = mock_redis  # noqa: SLF001

    data = await loader.load(_SNAPSHOT_ID)
    assert data["market"] == "US"
    mock_redis.get.assert_awaited_once()
