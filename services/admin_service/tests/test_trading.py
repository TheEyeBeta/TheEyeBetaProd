"""Tests for Emergency Trading control plane."""

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


@pytest.fixture
async def trading_master_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        trading_mode="local",
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
async def trading_operator_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        trading_mode="local",
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
def test_matrix_includes_trading_control_plane() -> None:
    from control_matrix.registry import build_control_matrix

    ids = {e.id for e in build_control_matrix()}
    assert "admin.trading.control-plane" in ids
    assert "trading.emergency-halt" in ids
    halt = next(e for e in build_control_matrix() if e.id == "trading.emergency-halt")
    assert halt.frontend_location == "/admin/emergency"
    assert halt.audit_implemented


@pytest.mark.unit
def test_require_dangerous_confirm_blocks_live_enable() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm

    body = DangerousActionRequest(reason="enable live", confirm=True)
    with pytest.raises(HTTPException):
        require_dangerous_confirm(body, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_forbidden_on_status(trading_operator_client: AsyncClient) -> None:
    resp = await trading_operator_client.get("/admin/trading/status")
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_visible(trading_master_client: AsyncClient) -> None:
    resp = await trading_master_client.get("/admin/trading/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["live_trading_enabled"] is False
    assert body["broker_mode"] in {"paper", "live"}
    assert "broker" in body
    assert "oms" in body
    assert "edge_api" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_emergency_page_renders(trading_master_client: AsyncClient) -> None:
    resp = await trading_master_client.get("/admin/emergency")
    assert resp.status_code == 200
    assert "Emergency Trading" in resp.text
    assert "Live trading" in resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_enable_requires_confirm(trading_master_client: AsyncClient) -> None:
    token_resp = await trading_master_client.post(
        "/admin/trading/live-approval-token",
        json={"reason": "issue token", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["token"]

    resp = await trading_master_client.post(
        "/admin/trading/live-approval",
        json={"token": token, "reason": "enable live", "confirm": False},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_enable_protected_flow(trading_master_client: AsyncClient) -> None:
    token_resp = await trading_master_client.post(
        "/admin/trading/live-approval-token",
        json={"reason": "prep live session", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    token = token_resp.json()["token"]

    resp = await trading_master_client.post(
        "/admin/trading/live-approval",
        json={"token": token, "reason": "approved by master admin", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["live_trading_enabled"] is True
    assert resp.json()["broker_mode"] == "live"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_halt_audited(trading_master_client: AsyncClient) -> None:
    resp = await trading_master_client.post(
        "/admin/trading/emergency-halt",
        json={"reason": "market shock", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["emergency_halt"] is True
    assert resp.json()["live_trading_enabled"] is False

    events = await trading_master_client.get("/admin/trading/events")
    assert any(e["event_type"] == "emergency_halt" for e in events.json()["events"])

    audit = await trading_master_client.get("/admin/audit/log")
    actions = {row["action"] for row in audit.json().get("entries", [])}
    assert "trading.emergency_halt" in actions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_audited_without_auto_live(trading_master_client: AsyncClient) -> None:
    await trading_master_client.post(
        "/admin/trading/emergency-halt",
        json={"reason": "halt before resume test", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    resp = await trading_master_client.post(
        "/admin/trading/resume-from-halt",
        json={"reason": "conditions normalized", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["emergency_halt"] is False
    assert body["live_trading_enabled"] is False

    history = await trading_master_client.get("/admin/trading/gate-history")
    types = {e["event_type"] for e in history.json()["entries"]}
    assert "resume_from_halt" in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_operator_forbidden_on_halt(trading_operator_client: AsyncClient) -> None:
    resp = await trading_operator_client.post(
        "/admin/trading/emergency-halt",
        json={"reason": "should fail", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403
