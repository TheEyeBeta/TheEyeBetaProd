"""Integration tests for control-plane JSON APIs."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_SQL_DIR = Path(__file__).resolve().parent / "sql"

if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from zinc_test._infra import _run_sql_file  # noqa: E402


@pytest.fixture(scope="session")
def control_plane_integration_dsn(admin_integration_dsn: str) -> str:
    """Postgres with worker/trask/alert seed data for control-plane tests."""
    _run_sql_file(admin_integration_dsn, _SQL_DIR / "seed_control_plane.sql")
    return admin_integration_dsn


async def _client_with_role(
    dsn: str,
    role: str,
) -> AsyncIterator[AsyncClient]:
    """HTTP client with a specific RBAC role override."""
    import importlib.util
    from unittest.mock import patch

    from auth import get_current_user  # noqa: PLC0415

    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location(
        "admin_conftest",
        _SERVICE_ROOT / "tests" / "conftest.py",
    )
    admin_conftest = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(admin_conftest)

    get_settings.cache_clear()
    settings = Settings(
        database_url=dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        admin_password_bcrypt="",
        jwt_private_key="",
        jwt_public_key="",
    )

    with (
        patch("deps.init_resources", admin_conftest._init_test_resources),
        patch("deps.close_resources", admin_conftest._close_test_resources),
    ):
        app = create_app(settings=settings)
        await admin_conftest._init_test_resources(settings)
        import deps  # noqa: PLC0415

        deps.bind_app_state(app, settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "test-operator", "role": role}

        app.dependency_overrides[get_current_user] = _fake_user
        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            await admin_conftest._close_test_resources()


@pytest.fixture
async def control_plane_client(
    control_plane_integration_dsn: str,
) -> AsyncIterator[AsyncClient]:
    """Client with MASTER_ADMIN role and control-plane seed."""
    async for client in _client_with_role(control_plane_integration_dsn, "MASTER_ADMIN"):
        yield client


@pytest.fixture
async def read_only_client(
    control_plane_integration_dsn: str,
) -> AsyncIterator[AsyncClient]:
    """Client with READ_ONLY role."""
    async for client in _client_with_role(control_plane_integration_dsn, "READ_ONLY"):
        yield client


@pytest.mark.asyncio
async def test_ops_pulse_returns_real_data(control_plane_client: AsyncClient) -> None:
    """GET /admin/ops/pulse aggregates worker/trask/alert tables."""
    resp = await control_plane_client.get(
        "/admin/ops/pulse",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["health"] in {"ok", "degraded", "critical"}
    assert body["pending_orders_count"] >= 0
    assert isinstance(body["open_breakers"], list)
    assert isinstance(body["critical_alerts"], list)
    assert isinstance(body["last_worker_runs"], list)
    assert "pipeline_freshness" in body


@pytest.mark.asyncio
async def test_workers_list(control_plane_client: AsyncClient) -> None:
    """GET /admin/workers returns registry entries."""
    resp = await control_plane_client.get(
        "/admin/workers",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(w["name"] == "MassiveDailyIngestionWorker" for w in body["workers"])


@pytest.mark.asyncio
async def test_worker_runs_paginated(control_plane_client: AsyncClient) -> None:
    """GET /admin/workers/runs supports pagination."""
    resp = await control_plane_client.get(
        "/admin/workers/runs",
        params={"limit": 5, "offset": 0},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 5
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_trask_dashboard(control_plane_client: AsyncClient) -> None:
    """GET /admin/trask/dashboard returns breaker and component state."""
    resp = await control_plane_client.get(
        "/admin/trask/dashboard",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["components_total"] >= 1
    assert isinstance(body["open_breakers"], list)


@pytest.mark.asyncio
async def test_alerts_list_and_ack(control_plane_client: AsyncClient) -> None:
    """GET /admin/alerts and POST ack work against audit_alerts."""
    list_resp = await control_plane_client.get(
        "/admin/alerts",
        headers={"Authorization": "Bearer test"},
    )
    assert list_resp.status_code == 200
    alerts = list_resp.json()["alerts"]
    assert len(alerts) >= 1
    alert_id = alerts[0]["id"]
    ack_resp = await control_plane_client.post(
        f"/admin/alerts/{alert_id}/ack",
        json={"note": "reviewed in test"},
        headers={"Authorization": "Bearer test"},
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["ack_state"] == "acked"


@pytest.mark.asyncio
async def test_prelive_cached(control_plane_client: AsyncClient) -> None:
    """GET /admin/prelive returns cached structured checks."""
    resp = await control_plane_client.get(
        "/admin/prelive",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall"] in {"pass", "fail", "stale"}
    assert isinstance(body["checks"], list)


@pytest.mark.asyncio
async def test_read_only_denied_worker_run(read_only_client: AsyncClient) -> None:
    """READ_ONLY operator cannot trigger worker runs."""
    resp = await read_only_client.post(
        "/admin/workers/macro-ingest/run",
        json={"dry_run": True, "force": False, "args": {}, "reason": "test"},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_read_only_can_access_pulse(read_only_client: AsyncClient) -> None:
    """READ_ONLY operator can read ops pulse."""
    resp = await read_only_client.get(
        "/admin/ops/pulse",
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_login_page_renders() -> None:
    """GET /admin/login returns HTML without auth."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    async def _init_noop(settings: object) -> None:  # noqa: ARG001
        return None

    async def _close_noop() -> None:
        return None

    get_settings.cache_clear()
    settings = Settings(
        database_url="postgresql://unused:unused@127.0.0.1:1/nodb",
        admin_password_bcrypt="x",
        jwt_private_key="x",
        jwt_public_key="x",
    )
    with (
        patch("deps.init_resources", _init_noop),
        patch("deps.close_resources", _close_noop),
    ):
        app = create_app(settings=settings)
        with TestClient(app) as client:
            resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Sign in" in resp.text
