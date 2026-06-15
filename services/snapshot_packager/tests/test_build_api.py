"""Tests for POST /snapshots/build."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import main as main_module
import pytest
from fastapi.testclient import TestClient
from main import create_app
from snapshot_packager.package import PackageResult


@pytest.mark.unit
def test_snapshots_build_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /snapshots/build returns packaging metadata."""
    result = PackageResult(
        market="US",
        trade_date=date(2025, 1, 15),
        snapshot_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        blob_uri="s3://theeyebeta-snapshots/packaged/US/2025/01/2025-01-15.json",
        sha256_hex="abc123",
        universe_size=1,
    )

    monkeypatch.setenv("INGEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/theeyebeta")

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()
    mock_consumer.run_forever = AsyncMock()

    with (
        patch("main.asyncpg.create_pool", AsyncMock(return_value=mock_pool)),
        patch("main.SnapshotPackagerService", return_value=mock_consumer),
        patch(
            "main.package_snapshot",
            new_callable=AsyncMock,
            return_value=result,
        ),
    ):
        client = TestClient(create_app())
        main_module._pool = mock_pool
        response = client.post(
            "/snapshots/build",
            json={"market": "US", "date": "2025-01-15"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["market"] == "US"
    assert body["date"] == "2025-01-15"
    assert body["blob_uri"].startswith("s3://")
