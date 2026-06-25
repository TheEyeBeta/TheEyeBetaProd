"""Tests for Risk cockpit control plane."""

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
def risk_integration_dsn(admin_integration_dsn: str) -> str:
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_risk.sql")
    return admin_integration_dsn


@pytest.fixture
async def risk_master_client(risk_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=risk_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        risk_default_portfolio_id="a660e8400-e29b-41d4-a716-446655440099",
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
async def risk_operator_client(risk_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=risk_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        risk_default_portfolio_id="a660e8400-e29b-41d4-a716-446655440099",
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
def test_matrix_includes_risk_control_plane() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.risk.control-plane" in ids
    assert "risk.override" in ids
    assert "risk.compute" in ids
    override = next(e for e in build_control_matrix() if e.id == "risk.override")
    assert override.frontend_location == "/admin/risk"
    assert override.audit_implemented


@pytest.mark.unit
def test_override_requires_confirm_header() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm
    from zinc_schemas.admin_dto import RiskOverrideRequest

    body = RiskOverrideRequest(
        check_name="portfolio_var_95",
        reason="temporary waiver for rebalance",
        confirm=True,
    )
    with pytest.raises(HTTPException):
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            None,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_can_read_status(risk_operator_client: AsyncClient) -> None:
    resp = await risk_operator_client.get("/admin/risk/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["portfolio_id"] == "a660e8400-e29b-41d4-a716-446655440099"
    assert body["active_breach_count"] >= 1
    assert isinstance(body["control_gaps"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_forbidden_on_compute(risk_operator_client: AsyncClient) -> None:
    resp = await risk_operator_client.post(
        "/admin/risk/compute",
        json={"reason": "refresh", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_audited(risk_master_client: AsyncClient) -> None:
    resp = await risk_master_client.post(
        "/admin/risk/compute",
        json={"reason": "manual refresh", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["audited"] is True
    assert body["portfolio_id"] == "a660e8400-e29b-41d4-a716-446655440099"
    assert body["mode"] in {"local", "remote"}

    history = await risk_master_client.get("/admin/risk/history")
    assert history.status_code == 200
    events = history.json()["entries"]
    assert any(e["event_type"] == "compute" for e in events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_override_requires_confirm(risk_master_client: AsyncClient) -> None:
    resp = await risk_master_client.post(
        "/admin/risk/override",
        json={
            "check_name": "portfolio_var_95",
            "reason": "one-time waiver",
            "confirm": True,
        },
    )
    assert resp.status_code == 422

    ok = await risk_master_client.post(
        "/admin/risk/override",
        json={
            "check_name": "portfolio_var_95",
            "reason": "one-time waiver",
            "confirm": True,
        },
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["audited"] is True
    assert body["check_name"] == "portfolio_var_95"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_breaches_and_failures(risk_master_client: AsyncClient) -> None:
    breaches = await risk_master_client.get("/admin/risk/breaches")
    assert breaches.status_code == 200
    assert len(breaches.json()["breaches"]) >= 1

    failures = await risk_master_client.get("/admin/risk/failures")
    assert failures.status_code == 200
    assert len(failures.json()["failures"]) >= 1
