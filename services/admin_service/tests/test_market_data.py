"""Tests for market data, pipelines, and snapshots control plane."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


def _run_sql_file(dsn: str, path: Path) -> None:
    from tests.conftest import _run_sql_file as run

    run(dsn, path)


@pytest.fixture
def market_integration_dsn(admin_integration_dsn: str) -> str:
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_market.sql")
    return admin_integration_dsn


@pytest.fixture
async def market_master_client(market_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=market_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
    )
    with (
        patch("main.init_resources", _init_test_resources),
        patch("main.close_resources", _close_test_resources),
    ):
        app = create_app(settings)

        async def _master() -> dict[str, Any]:
            return {"sub": "master-admin", "roles": ["MASTER_ADMIN", "operator"]}

        app.dependency_overrides[get_current_user] = _master
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.fixture
async def market_operator_client(market_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=market_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
    )
    with (
        patch("main.init_resources", _init_test_resources),
        patch("main.close_resources", _close_test_resources),
    ):
        app = create_app(settings)

        async def _operator() -> dict[str, Any]:
            return {"sub": "operator-one", "roles": ["operator"]}

        app.dependency_overrides[get_current_user] = _operator
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.mark.unit
def test_matrix_includes_market_entries() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.market-data.status" in ids
    assert "market.backfill" in ids
    assert "market.gap.resolve" in ids
    assert "admin.snapshots.list" in ids
    assert "snapshot.build" in ids
    assert "admin.pipelines.status" in ids


@pytest.mark.unit
def test_matrix_includes_sector_universe_entries() -> None:
    from control_matrix.registry import build_control_matrix

    ids = {e.id for e in build_control_matrix()}
    assert "admin.sectors.rotation" in ids
    assert "admin.sectors.breadth" in ids
    assert "admin.sectors.performance" in ids
    assert "admin.universe.caps" in ids
    assert "admin.universe.churn" in ids


@pytest.mark.unit
def test_gap_resolve_requires_confirm() -> None:
    from fastapi import HTTPException
    from rbac import require_dangerous_confirm
    from zinc_schemas.admin_dto import MarketDataGapResolveRequest

    body = MarketDataGapResolveRequest(reason="verified manually", confirm=True)
    with pytest.raises(HTTPException):
        require_dangerous_confirm(body, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_market_status_safe_for_operator(market_operator_client: AsyncClient) -> None:
    resp = await market_operator_client.get("/admin/market-data/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "ingestion_health" in body
    assert "data_api_public_routes" in body
    assert isinstance(body["data_api_public_routes"], list)
    assert len(body["data_api_public_routes"]) == 2
    hostnames = {row["hostname"] for row in body["data_api_public_routes"]}
    assert "dataapi.theeyebeta.store" in hostnames
    assert "dataapiprod.theeyebeta.store" in hostnames
    assert body["open_gap_count"] >= 2
    assert isinstance(body["control_gaps"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_market_data_html_shows_public_route_health(market_operator_client: AsyncClient) -> None:
    resp = await market_operator_client.get(
        "/admin/market-data",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "dataapi.theeyebeta.store" in body
    assert "dataapiprod.theeyebeta.store" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_gap_resolve_audited(market_master_client: AsyncClient) -> None:
    gaps = await market_master_client.get("/admin/market-data/gaps")
    gap_id = gaps.json()["gaps"][0]["id"]
    blocked = await market_master_client.post(
        f"/admin/market-data/gaps/{gap_id}/resolve",
        json={"reason": "filled via alternate ingest", "confirm": True},
    )
    assert blocked.status_code == 422

    ok = await market_master_client.post(
        f"/admin/market-data/gaps/{gap_id}/resolve",
        json={"reason": "filled via alternate ingest", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    assert ok.json()["audited"] is True
    assert ok.json()["remediation_state"] == "RESOLVED"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_protected(market_master_client: AsyncClient) -> None:
    blocked = await market_master_client.post(
        "/admin/market-data/backfill",
        json={"reason": "rerun daily pipeline", "confirm": True},
    )
    assert blocked.status_code == 422

    ok = await market_master_client.post(
        "/admin/market-data/backfill",
        json={"reason": "rerun daily pipeline", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    assert ok.json()["audited"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshot_build_protected(market_master_client: AsyncClient) -> None:
    blocked = await market_master_client.post(
        "/admin/snapshots/build",
        json={
            "market": "US",
            "trading_date": "2026-06-17",
            "reason": "rebuild test",
            "confirm": True,
        },
    )
    assert blocked.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipelines_status_for_operator(market_operator_client: AsyncClient) -> None:
    resp = await market_operator_client.get("/admin/pipelines")
    assert resp.status_code == 200
    body = resp.json()
    assert "workers" in body
    assert "ingestion_metrics" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshots_list_for_operator(market_operator_client: AsyncClient) -> None:
    resp = await market_operator_client.get("/admin/snapshots")
    assert resp.status_code == 200
    body = resp.json()
    assert "snapshots" in body
