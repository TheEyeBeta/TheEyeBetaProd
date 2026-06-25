"""Tests for Legal/Compliance cockpit control plane."""

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
def compliance_integration_dsn(admin_integration_dsn: str) -> str:
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_compliance.sql")
    return admin_integration_dsn


@pytest.fixture
async def compliance_master_client(compliance_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=compliance_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        compliance_default_portfolio_id="b770e8400-e29b-41d4-a716-446655440088",
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
async def compliance_operator_client(compliance_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=compliance_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        compliance_default_portfolio_id="b770e8400-e29b-41d4-a716-446655440088",
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
def test_matrix_includes_compliance_control_plane() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.compliance.control-plane" in ids
    assert "compliance.override" in ids
    assert "compliance.legal-hold" in ids
    override = next(e for e in build_control_matrix() if e.id == "compliance.override")
    assert override.frontend_location == "/admin/compliance"
    assert override.audit_implemented


@pytest.mark.unit
def test_override_requires_confirm_header() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm
    from zinc_schemas.admin_dto import ComplianceOverrideRequest

    body = ComplianceOverrideRequest(
        rule_id="wash_sale",
        reason="documented waiver",
        confirm=True,
    )
    with pytest.raises(HTTPException):
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            None,
        )


@pytest.mark.unit
def test_legal_hold_requires_confirm_header() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm
    from zinc_schemas.admin_dto import ComplianceLegalHoldRequest

    body = ComplianceLegalHoldRequest(
        action="apply",
        entity_type="portfolio",
        entity_id="b770e8400-e29b-41d4-a716-446655440088",
        reason="litigation hold",
        confirm=True,
    )
    with pytest.raises(HTTPException):
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            None,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_can_read_status(compliance_operator_client: AsyncClient) -> None:
    resp = await compliance_operator_client.get("/admin/compliance/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["portfolio_id"] == "b770e8400-e29b-41d4-a716-446655440088"
    assert body["recent_failed_count"] >= 1
    assert len(body["rule_catalog"]) == 5
    assert isinstance(body["control_gaps"], list)
    assert any(g["action"] == "legal_hold_enforcement" for g in body["control_gaps"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_forbidden_on_override(compliance_operator_client: AsyncClient) -> None:
    resp = await compliance_operator_client.post(
        "/admin/compliance/override",
        json={"rule_id": "wash_sale", "reason": "waiver", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rules_patch_audited(compliance_master_client: AsyncClient) -> None:
    resp = await compliance_master_client.patch(
        "/admin/compliance/rules",
        json={
            "rules": {"max_day_trades_5d": 4},
            "reason": "policy update",
            "confirm": True,
        },
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rules"]["max_day_trades_5d"] == 4
    assert body["version"] >= 2

    history = await compliance_master_client.get("/admin/compliance/history")
    assert history.status_code == 200
    events = history.json()["entries"]
    assert any(e["event_type"] == "rules_patch" for e in events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_override_and_legal_hold_protected(compliance_master_client: AsyncClient) -> None:
    missing = await compliance_master_client.post(
        "/admin/compliance/override",
        json={"rule_id": "wash_sale", "reason": "waiver", "confirm": True},
    )
    assert missing.status_code == 422

    ok = await compliance_master_client.post(
        "/admin/compliance/override",
        json={"rule_id": "wash_sale", "reason": "waiver", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    assert ok.json()["audited"] is True

    hold = await compliance_master_client.post(
        "/admin/compliance/legal-hold",
        json={
            "action": "apply",
            "entity_type": "portfolio",
            "entity_id": "b770e8400-e29b-41d4-a716-446655440088",
            "reason": "litigation",
            "confirm": True,
        },
        headers={"X-Confirm": "true"},
    )
    assert hold.status_code == 200
    assert hold.json()["audited"] is True
    assert hold.json()["active"] is True
