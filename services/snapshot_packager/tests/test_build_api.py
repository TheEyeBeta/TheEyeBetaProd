"""Tests for POST /snapshots/build."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from snapshot_packager.package import PackageResult

_MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
_SPEC = importlib.util.spec_from_file_location("snapshot_packager_main", _MAIN_PATH)
assert _SPEC is not None and _SPEC.loader is not None
main_module = importlib.util.module_from_spec(_SPEC)
sys.modules["snapshot_packager_main"] = main_module
_SPEC.loader.exec_module(main_module)


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

    monkeypatch.setenv(
        "INGEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/theeyebeta"
    )

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()
    mock_consumer.run_forever = AsyncMock()

    with (
        patch.object(main_module.asyncpg, "create_pool", AsyncMock(return_value=mock_pool)),
        patch.object(main_module, "SnapshotPackagerService", return_value=mock_consumer),
        patch.object(main_module, "package_snapshot", AsyncMock(return_value=result)),
    ):
        client = TestClient(main_module.create_app())
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
