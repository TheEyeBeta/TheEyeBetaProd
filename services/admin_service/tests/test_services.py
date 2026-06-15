"""Integration tests for admin services (systemd) API."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from api.services import ALL_UNITS, RESTARTABLE_SERVICES
from httpx import AsyncClient


def _fake_proc(
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    """Mock subprocess whose communicate() resolves immediately."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _show_stdout(
    active: str = "active",
    sub: str = "running",
    ts: str = "Thu 2026-06-12 10:00:00 UTC",
) -> bytes:
    """Simulate ``systemctl show`` stdout for a healthy unit."""
    return (
        f"ActiveState={active}\n"
        f"SubState={sub}\n"
        f"ActiveEnterTimestamp={ts}\n"
    ).encode()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_lists_all_units(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/services/status returns all known systemd units."""
    client, _ = admin_client
    show = _fake_proc(stdout=_show_stdout())
    with patch(
        "api.services.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await client.get("/admin/services/status", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["network"] == "systemd"
    assert len(body["services"]) == len(ALL_UNITS)
    assert {s["name"] for s in body["services"]} == set(ALL_UNITS.keys())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_active_unit_is_healthy(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Active units report healthy in the status response."""
    client, _ = admin_client
    show = _fake_proc(stdout=_show_stdout(active="active", sub="running"))
    with patch(
        "api.services.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await client.get("/admin/services/status", headers=auth_headers)

    entries = {s["name"]: s for s in resp.json()["services"]}
    assert entries["admin-service"]["health"] == "healthy"
    assert "active" in entries["admin-service"]["state"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_inactive_unit_is_unhealthy(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Inactive units report unhealthy in the status response."""
    client, _ = admin_client
    show = _fake_proc(stdout=_show_stdout(active="inactive", sub="dead"))
    with patch(
        "api.services.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=show),
    ):
        resp = await client.get("/admin/services/status", headers=auth_headers)

    entry = next(s for s in resp.json()["services"] if s["name"] == "admin-service")
    assert entry["health"] == "unhealthy"
    assert "inactive" in entry["state"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_requires_auth(admin_integration_dsn: str) -> None:
    """GET /admin/services/status rejects unauthenticated requests."""
    from conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(database_url=admin_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/services/status")
    assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_whitelisted_service(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/services/{name}/restart restarts a whitelisted unit."""
    client, _ = admin_client
    restart_proc = _fake_proc(returncode=0)
    show_proc = _fake_proc(stdout=_show_stdout())

    with (
        patch(
            "api.services.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[restart_proc, show_proc]),
        ),
        patch("api.services.asyncio.sleep", new=AsyncMock()),
        patch("api.services.write_audit_log", new=AsyncMock()),
    ):
        resp = await client.post(
            "/admin/services/admin-service/restart",
            json={"reason": "test restart", "timeout_seconds": 30},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "admin-service"
    assert body["restarted"] is True
    assert body["state"] == "active"
    assert body["container_id"] == "theeyebeta-admin"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_calls_correct_unit(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Verify the correct systemd unit name is passed to systemctl."""
    client, _ = admin_client
    mock_exec = AsyncMock(
        side_effect=[
            _fake_proc(returncode=0),
            _fake_proc(stdout=_show_stdout()),
        ]
    )

    with (
        patch("api.services.asyncio.create_subprocess_exec", new=mock_exec),
        patch("api.services.asyncio.sleep", new=AsyncMock()),
        patch("api.services.write_audit_log", new=AsyncMock()),
    ):
        await client.post(
            "/admin/services/llm-gateway/restart",
            json={"reason": "test", "timeout_seconds": 10},
            headers=auth_headers,
        )

    first_args = mock_exec.call_args_list[0][0]
    assert first_args == ("sudo", "systemctl", "restart", "theeyebeta-litellm")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_unknown_service_returns_422(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Names outside the whitelist return 422."""
    client, _ = admin_client
    resp = await client.post(
        "/admin/services/not-a-service/restart",
        json={"reason": "test", "timeout_seconds": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "whitelist" in resp.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_systemctl_failure_returns_409(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """systemctl restart failure surfaces as 409."""
    client, _ = admin_client
    fail_proc = _fake_proc(returncode=1, stderr=b"Job for theeyebeta-admin.service failed")

    with (
        patch(
            "api.services.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fail_proc),
        ),
        patch("api.services.asyncio.sleep", new=AsyncMock()),
    ):
        resp = await client.post(
            "/admin/services/admin-service/restart",
            json={"reason": "test", "timeout_seconds": 10},
            headers=auth_headers,
        )

    assert resp.status_code == 409
    assert "systemctl refused" in resp.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_requires_auth(admin_integration_dsn: str) -> None:
    """POST /admin/services/{name}/restart rejects unauthenticated requests."""
    from conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(database_url=admin_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/admin/services/admin-service/restart",
                json={"reason": "test", "timeout_seconds": 10},
            )
    assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_writes_audit_log(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Successful restart writes an audit log entry."""
    client, _ = admin_client
    mock_audit = AsyncMock()

    with (
        patch(
            "api.services.asyncio.create_subprocess_exec",
            new=AsyncMock(
                side_effect=[
                    _fake_proc(returncode=0),
                    _fake_proc(stdout=_show_stdout()),
                ]
            ),
        ),
        patch("api.services.asyncio.sleep", new=AsyncMock()),
        patch("api.services.write_audit_log", new=mock_audit),
    ):
        await client.post(
            "/admin/services/admin-service/restart",
            json={"reason": "scheduled maintenance", "timeout_seconds": 10},
            headers=auth_headers,
        )

    mock_audit.assert_awaited_once()
    kw = mock_audit.call_args.kwargs
    assert kw["action"] == "restart.service"
    assert kw["entity_type"] == "service"
    assert kw["entity_id"] == "admin-service"
    assert kw["payload"]["unit"] == "theeyebeta-admin"


def test_restartable_services_have_non_empty_units() -> None:
    """Every restartable service maps to a non-empty systemd unit name."""
    for name, unit in RESTARTABLE_SERVICES.items():
        assert unit, f"{name!r} maps to an empty unit name"


def test_all_units_is_superset_of_restartable() -> None:
    """ALL_UNITS includes every restartable service."""
    for name in RESTARTABLE_SERVICES:
        assert name in ALL_UNITS, (
            f"{name!r} is in RESTARTABLE_SERVICES but missing from ALL_UNITS"
        )


def test_no_docker_imports() -> None:
    """Guard against docker-py imports creeping back into the services module."""
    import inspect

    import api.services as svc_module

    src = inspect.getsource(svc_module)
    assert "import docker" not in src
    assert "from docker" not in src
