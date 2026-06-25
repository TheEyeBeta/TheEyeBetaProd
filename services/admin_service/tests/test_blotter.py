"""Tests for OMS/Broker/Portfolio blotter."""

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
def blotter_integration_dsn(admin_integration_dsn: str) -> str:
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_orders.sql")
    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_blotter.sql")
    return admin_integration_dsn


@pytest.fixture
async def blotter_master_client(blotter_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=blotter_integration_dsn,
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
async def blotter_operator_client(blotter_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=blotter_integration_dsn,
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
def test_matrix_includes_blotter_entries() -> None:
    from control_matrix.registry import MATRIX_VERSION, build_control_matrix

    assert MATRIX_VERSION == "2026-06-24.14"
    ids = {e.id for e in build_control_matrix()}
    assert "admin.orders.blotter" in ids
    assert "admin.broker.blotter" in ids
    assert "oms.reconciliation.resolve" in ids


@pytest.mark.unit
def test_reconciliation_resolve_requires_confirm() -> None:
    from fastapi import HTTPException
    from rbac import DangerousActionRequest, require_dangerous_confirm

    body = DangerousActionRequest(reason="drift cleared manually", confirm=True)
    with pytest.raises(HTTPException):
        require_dangerous_confirm(body, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_broker_status_safe_for_operator(blotter_operator_client: AsyncClient) -> None:
    resp = await blotter_operator_client.get("/admin/broker/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "broker_mode" in body
    assert isinstance(body["control_gaps"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_lifecycle_visible(blotter_operator_client: AsyncClient) -> None:
    listing = await blotter_operator_client.get("/admin/orders")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    order_id = body["orders"][0]["id"]
    events = await blotter_operator_client.get(f"/admin/orders/{order_id}/events")
    assert events.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_requires_confirm(blotter_master_client: AsyncClient) -> None:
    pending = await blotter_master_client.get("/admin/orders/pending")
    order_id = pending.json()["orders"][0]["id"]
    missing = await blotter_master_client.post(
        f"/admin/orders/{order_id}/approve",
        json={"reason": "ops approve", "confirm": True},
    )
    assert missing.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconciliation_resolve_protected(blotter_master_client: AsyncClient) -> None:
    recon = await blotter_master_client.get("/admin/oms/reconciliation")
    assert recon.status_code == 200
    blocked = await blotter_master_client.post(
        "/admin/oms/reconciliation/resolve",
        json={"reason": "manual clear", "confirm": True},
    )
    assert blocked.status_code == 422

    ok = await blotter_master_client.post(
        "/admin/oms/reconciliation/resolve",
        json={"reason": "manual clear", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert ok.status_code == 200
    assert ok.json()["audited"] is True
