"""Tests for Services/systemd control plane."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from services_control.registry import CANONICAL_SERVICES, service_by_key


def _fake_proc(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _show_stdout(
    active: str = "active",
    sub: str = "running",
    ts: str = "Thu 2026-06-12 10:00:00 UTC",
) -> bytes:
    return (
        f"ActiveState={active}\n"
        f"SubState={sub}\n"
        f"UnitFileState=enabled\n"
        f"ActiveEnterTimestamp={ts}\n"
        f"NRestarts=2\n"
        f"MemoryCurrent=1048576\n"
        f"CPUUsageNSec=999\n"
    ).encode()


@pytest.fixture
async def services_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        services_mode="local",
    )
    with (
        patch("main.init_resources", _init_test_resources),
        patch("main.close_resources", _close_test_resources),
    ):
        app = create_app(settings)

        async def _operator() -> dict[str, Any]:
            return {"sub": "test-operator", "roles": ["operator"]}

        app.dependency_overrides[get_current_user] = _operator
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.fixture
async def services_master_client(admin_integration_dsn: str) -> AsyncClient:
    from auth import get_current_user
    from main import create_app
    from settings import Settings, get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = Settings.model_construct(
        database_url=admin_integration_dsn,
        nats_url="nats://127.0.0.1:4222",
        redis_url="redis://127.0.0.1:6379/15",
        services_mode="local",
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
def test_matrix_includes_services_control_plane() -> None:
    from control_matrix.registry import build_control_matrix

    ids = {e.id for e in build_control_matrix()}
    assert "admin.services.control-plane" in ids
    data_api = next(e for e in build_control_matrix() if e.id == "service.systemd.data-api")
    assert data_api.frontend_location == "/admin/services"
    assert data_api.service_port_dependency == "127.0.0.1:7000"


@pytest.mark.unit
def test_data_api_maps_to_port_7000_and_hostnames() -> None:
    svc = service_by_key("data-api")
    assert svc is not None
    assert svc.port == 7000
    assert svc.systemd_unit == "theeyebeta-dataapi"
    assert "dataapi.theeyebeta.store" in svc.hostnames
    assert "dataapiprod.theeyebeta.store" in svc.hostnames
    assert svc.health_endpoint == "/health"


@pytest.mark.unit
def test_port_registry_excludes_9500_as_expected() -> None:
    from edge.canonical_routes import UNREGISTERED_INCIDENT_PORTS
    from services_control.registry import expected_ports

    registered = set(expected_ports().keys())
    assert 7000 in registered
    assert 9500 not in registered
    assert 9500 in UNREGISTERED_INCIDENT_PORTS


@pytest.mark.unit
def test_allowlisted_systemd_rejects_unknown_unit() -> None:
    from services_control.systemd_probe import AllowlistedSystemdProbe

    probe = AllowlistedSystemdProbe(allowed_units=frozenset({"theeyebeta-admin"}), enabled=False)
    with pytest.raises(ValueError, match="not allowlisted"):
        __import__("asyncio").run(probe.restart("evil-unit"))


@pytest.mark.unit
def test_logs_bounded_and_sanitized() -> None:
    from services_control.logs import MAX_LOG_LINES, sanitize_log_lines

    raw = [f"token=secret-{i} " + ("x" * 5000) for i in range(200)]
    lines = sanitize_log_lines(raw, limit=MAX_LOG_LINES)
    assert len(lines) == MAX_LOG_LINES
    assert all("secret-" not in line for line in lines)
    assert all(len(line) <= 4003 for line in lines)


@pytest.mark.unit
def test_all_services_have_allowlisted_units() -> None:
    assert len(CANONICAL_SERVICES) >= 9
    for svc in CANONICAL_SERVICES:
        assert svc.systemd_unit
        assert svc.key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_services_allowlist(services_client: AsyncClient) -> None:
    show = _fake_proc(stdout=_show_stdout())
    with patch(
        "services_control.systemd_probe.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await services_client.get("/admin/services")
    assert resp.status_code == 200
    body = resp.json()
    names = {row["name"] for row in body["services"]}
    assert "data-api" in names
    assert "admin-service" in names
    assert len(names) == len(CANONICAL_SERVICES)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_service_rejected(services_client: AsyncClient) -> None:
    resp = await services_client.get("/admin/services/not-real")
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ports_endpoint_marks_9500_unexpected(services_client: AsyncClient) -> None:
    with patch(
        "services_control.service.is_port_listening",
        new=AsyncMock(return_value=False),
    ):
        resp = await services_client.get("/admin/services/ports")
    assert resp.status_code == 200
    body = resp.json()
    data_api = next(row for row in body["ports"] if row["service_name"] == "data-api")
    assert data_api["port"] == 7000
    assert data_api["expected"] is True
    sentinel = next(row for row in body["ports"] if row["port"] == 9500)
    assert sentinel["expected"] is False
    assert 9500 in body["unregistered_incident_ports"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_audited(services_client: AsyncClient) -> None:
    restart_proc = _fake_proc(returncode=0)
    show_proc = _fake_proc(stdout=_show_stdout())
    with (
        patch(
            "services_control.systemd_probe.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[restart_proc, show_proc]),
        ),
    ):
        resp = await services_client.post(
            "/admin/services/admin-service/restart",
            json={"reason": "scheduled maintenance"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["audited"] is True
    assert body["action"] == "restart"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_unknown_service_rejected(services_client: AsyncClient) -> None:
    resp = await services_client.post(
        "/admin/services/evil-service/restart",
        json={"reason": "nope"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_critical_stop_requires_master_admin(services_client: AsyncClient) -> None:
    resp = await services_client.post(
        "/admin/services/data-api/stop",
        json={"reason": "should fail", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_disable_requires_master_admin(services_client: AsyncClient) -> None:
    resp = await services_client.post(
        "/admin/services/llm-gateway/disable",
        json={"reason": "should fail", "confirm": True},
        headers={"X-Confirm": "true"},
    )
    assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_master_can_disable_with_confirm(services_master_client: AsyncClient) -> None:
    disable_proc = _fake_proc(returncode=0)
    with patch(
        "services_control.systemd_probe.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=disable_proc),
    ):
        resp = await services_master_client.post(
            "/admin/services/llm-gateway/disable",
            json={"reason": "maintenance", "confirm": True},
            headers={"X-Confirm": "true"},
        )
    assert resp.status_code == 200
    assert resp.json()["audited"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_logs_bounded(services_client: AsyncClient) -> None:
    journal_proc = _fake_proc(
        stdout=b"\n".join(
            [f"token=abc line {i}".encode() for i in range(150)],
        ),
    )
    with patch(
        "services_control.systemd_probe.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=journal_proc),
    ):
        resp = await services_client.get("/admin/services/admin-service/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bounded"] is True
    assert len(body["lines"]) <= 100
    assert all("abc" not in row["line"] for row in body["lines"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_legacy_status_lists_all_units(
    services_client: AsyncClient,
) -> None:
    show = _fake_proc(stdout=_show_stdout())
    with patch(
        "services_control.systemd_probe.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await services_client.get("/admin/services/status")
    assert resp.status_code == 200
    assert len(resp.json()["services"]) == len(CANONICAL_SERVICES)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_services_page_renders_html(services_client: AsyncClient) -> None:
    show = _fake_proc(stdout=_show_stdout())
    with patch(
        "services_control.systemd_probe.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await services_client.get(
            "/admin/services",
            headers={"Accept": "text/html"},
        )
    assert resp.status_code == 200
    assert "Services / systemd" in resp.text
    assert "data-api" in resp.text
