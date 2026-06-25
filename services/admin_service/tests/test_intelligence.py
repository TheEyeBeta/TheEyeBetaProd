"""Tests for intelligence control plane (Prompt 14)."""

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
def intelligence_integration_dsn(admin_integration_dsn: str) -> str:
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_intelligence.sql")
    return admin_integration_dsn


@pytest.fixture
async def intel_master_client(intelligence_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=intelligence_integration_dsn,
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
async def intel_operator_client(intelligence_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=intelligence_integration_dsn,
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
def test_matrix_includes_intelligence_entries() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.agents.detail" in ids
    assert "agent.run" in ids
    assert "admin.proposals.actions" in ids
    assert "admin.backtests.cockpit" in ids
    assert "admin.reports.cockpit" in ids
    assert "costs.kill_switch" in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_overview_visible(intel_operator_client: AsyncClient) -> None:
    resp = await intel_operator_client.get("/admin/costs")
    assert resp.status_code == 200
    body = resp.json()
    assert "kill_switch_active" in body
    assert "total_cost_usd" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kill_switch_protected(intel_master_client: AsyncClient) -> None:
    blocked = await intel_master_client.post(
        "/admin/costs/kill-switch",
        json={"active": True, "reason": "runaway spend", "confirm": True},
    )
    assert blocked.status_code == 422
    ok = await intel_master_client.post(
        "/admin/costs/kill-switch",
        json={"active": True, "reason": "runaway spend", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    assert ok.json()["kill_switch_active"] is True
    assert ok.json()["audited"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reports_list_visible(intel_operator_client: AsyncClient) -> None:
    resp = await intel_operator_client.get("/admin/reports")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["briefings"]) >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backtests_page_json(intel_operator_client: AsyncClient) -> None:
    resp = await intel_operator_client.get("/admin/backtests")
    assert resp.status_code == 200
    assert "runs" in resp.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_detail_visible(intel_operator_client: AsyncClient) -> None:
    listing = await intel_operator_client.get("/admin/agents")
    agent_id = listing.json()["agents"][0]["id"]
    detail = await intel_operator_client.get(f"/admin/agents/{agent_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == agent_id
    assert "open_violation_count" in body
