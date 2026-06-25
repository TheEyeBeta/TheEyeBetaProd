"""Tests for Workers/Schedulers control plane."""

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


@pytest.fixture(scope="session")
def workers_integration_dsn(admin_integration_dsn: str) -> str:
    from tests.conftest import _run_sql_file

    _run_sql_file(admin_integration_dsn, Path(__file__).parent / "sql" / "seed_workers.sql")
    return admin_integration_dsn


@pytest.fixture
async def workers_operator_client(workers_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=workers_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        workers_mode="local",
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


@pytest.fixture
async def workers_master_client(workers_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=workers_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        workers_mode="local",
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


@pytest.mark.unit
def test_matrix_includes_workers_control_plane() -> None:
    from control_matrix.registry import build_control_matrix

    ids = {e.id for e in build_control_matrix()}
    assert "admin.workers.control-plane" in ids
    gap_sentinel = next(e for e in build_control_matrix() if e.id == "worker.gap-sentinel")
    assert gap_sentinel.viewable
    assert gap_sentinel.frontend_location == "/admin/workers"
    assert gap_sentinel.audit_implemented


@pytest.mark.unit
def test_registry_lists_canonical_workers() -> None:
    from workers_control.registry import CANONICAL_WORKERS, all_worker_keys

    assert "gap-sentinel" in all_worker_keys()
    assert len(CANONICAL_WORKERS) >= 9


@pytest.mark.integration
@pytest.mark.unit
async def test_operator_can_list_workers(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.get("/admin/workers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["audit_tables_available"] is True
    names = {row["name"] for row in body["workers"]}
    assert "gap-sentinel" in names
    assert "backup" in names


@pytest.mark.integration
@pytest.mark.unit
async def test_workers_page_renders_html(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.get(
        "/admin/workers",
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "Workers / Schedulers" in resp.text
    assert "gap-sentinel" in resp.text


@pytest.mark.integration
@pytest.mark.unit
async def test_worker_detail_includes_runs_and_gaps(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.get("/admin/workers/gap-sentinel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["audit_worker_name"] == "GapSentinelWorker"
    assert body["runs"]
    assert any(g["action"] == "pause" for g in body["control_gaps"])


@pytest.mark.integration
@pytest.mark.unit
async def test_operator_forbidden_on_force_run(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.post(
        "/admin/workers/gap-sentinel/run",
        json={"reason": "should fail", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.unit
async def test_force_run_requires_confirm(workers_master_client: AsyncClient) -> None:
    resp = await workers_master_client.post(
        "/admin/workers/gap-sentinel/run",
        json={"reason": "manual test", "confirm": False},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.unit
async def test_force_run_audited(workers_master_client: AsyncClient) -> None:
    resp = await workers_master_client.post(
        "/admin/workers/gap-sentinel/run",
        json={"reason": "integration force run", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["audited"] is True
    assert body["action"] == "run"

    audit = await workers_master_client.get("/admin/audit/log")
    assert audit.status_code == 200
    actions = {row["action"] for row in audit.json().get("entries", [])}
    assert "workers.run" in actions


@pytest.mark.integration
@pytest.mark.unit
async def test_operator_forbidden_on_timer_disable(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.post(
        "/admin/timers/gap-sentinel/disable",
        json={"reason": "should fail", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.unit
async def test_master_can_disable_timer(workers_master_client: AsyncClient) -> None:
    resp = await workers_master_client.post(
        "/admin/timers/gap-sentinel/disable",
        json={"reason": "maintenance window", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["audited"] is True

    detail = await workers_master_client.get("/admin/timers/gap-sentinel")
    assert detail.status_code == 200
    assert detail.json()["enabled"] is False


@pytest.mark.integration
@pytest.mark.unit
async def test_backup_shows_stop_gap(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.get("/admin/workers/backup")
    assert resp.status_code == 200
    gaps = {g["action"] for g in resp.json()["control_gaps"]}
    assert "stop" in gaps
    assert resp.json()["supports_stop"] is False


@pytest.mark.integration
@pytest.mark.unit
async def test_timers_list_maps_workers(workers_operator_client: AsyncClient) -> None:
    resp = await workers_operator_client.get("/admin/timers")
    assert resp.status_code == 200
    timers = resp.json()["timers"]
    assert any(t["name"] == "gap-sentinel" and t["worker_key"] == "gap-sentinel" for t in timers)
