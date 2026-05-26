"""Integration tests for admin services (Docker control) API."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from docker.errors import NotFound
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)
_normalize_psycopg_dsn = _admin_conf._normalize_psycopg_dsn


def _audit_count(dsn: str, entity_id: str, action: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s AND action = %s
            """,
            (entity_id, action),
        ).fetchone()
    return int(row[0]) if row else 0


class _FakeContainer:
    """Minimal docker-py container stub."""

    def __init__(
        self,
        *,
        name: str,
        image: str,
        state: str = "running",
        health: str | None = "healthy",
    ) -> None:
        self.id = f"id-{name}"
        self.name = name
        started = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        health_block = {"Status": health} if health else None
        self.attrs: dict[str, Any] = {
            "Id": self.id,
            "Name": f"/{name}",
            "Image": image,
            "Config": {"Image": image},
            "State": {
                "Status": state,
                "Running": state == "running",
                "StartedAt": started,
                "Health": health_block,
            },
        }
        self.restart_calls: list[dict[str, Any]] = []

    def restart(self, *, timeout: int = 10) -> None:
        self.restart_calls.append({"timeout": timeout})
        self.attrs["State"]["Status"] = "running"
        self.attrs["State"]["Running"] = True

    def reload(self) -> None:
        return None


class _FakeNetwork:
    def __init__(self, container_ids: list[str]) -> None:
        self.attrs = {"Containers": dict.fromkeys(container_ids, {})}

    def reload(self) -> None:
        return None


class _FakeContainersCollection:
    def __init__(self, containers: list[_FakeContainer]) -> None:
        self._by_id = {c.id: c for c in containers}
        self._by_name = {c.name: c for c in containers}
        self._all = containers

    def list(self, *, all: bool = False) -> list[_FakeContainer]:  # noqa: A002 — match docker-py
        del all
        return list(self._all)

    def get(self, key: str) -> _FakeContainer:
        if key in self._by_id:
            return self._by_id[key]
        if key in self._by_name:
            return self._by_name[key]
        raise NotFound(f"container {key} not found")


class _FakeNetworksCollection:
    def __init__(self, network: _FakeNetwork | None) -> None:
        self._network = network

    def get(self, name: str) -> _FakeNetwork:
        if self._network is None or name != "theeyebeta-net":
            raise NotFound(f"network {name} not found")
        return self._network


class _FakeDockerClient:
    def __init__(
        self,
        containers: list[_FakeContainer],
        *,
        with_network: bool = True,
    ) -> None:
        self.containers = _FakeContainersCollection(containers)
        network = _FakeNetwork([c.id for c in containers]) if with_network else None
        self.networks = _FakeNetworksCollection(network)

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def _seed_containers() -> list[_FakeContainer]:
    return [
        _FakeContainer(
            name="oms",
            image="ghcr.io/theeyebeta/oms:latest",
            state="running",
            health="healthy",
        ),
        _FakeContainer(
            name="risk-service",
            image="ghcr.io/theeyebeta/risk-service:latest",
            state="running",
            health=None,
        ),
    ]


async def _services_client(
    dsn: str,
    docker_client: _FakeDockerClient,
) -> AsyncIterator[AsyncClient]:
    """Yield an httpx client wired to ``dsn`` and a fake Docker client."""
    from auth import get_current_user  # noqa: PLC0415
    from deps import get_docker  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "test-operator"}

        app.dependency_overrides[get_current_user] = _fake_user
        app.dependency_overrides[get_docker] = lambda: docker_client

        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        app.dependency_overrides.clear()


@pytest.fixture
async def services_client(
    admin_integration_dsn: str,
) -> AsyncIterator[tuple[AsyncClient, _FakeDockerClient]]:
    """Authed httpx client + fake Docker client (seeded)."""
    fake = _FakeDockerClient(_seed_containers())
    async for client in _services_client(admin_integration_dsn, fake):
        yield client, fake


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_happy(
    services_client: tuple[AsyncClient, _FakeDockerClient],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/services/status returns containers on theeyebeta-net."""
    client, _ = services_client
    response = await client.get("/admin/services/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["network"] == "theeyebeta-net"
    names = {row["name"] for row in body["services"]}
    assert {"oms", "risk-service"} <= names
    oms_row = next(row for row in body["services"] if row["name"] == "oms")
    assert oms_row["state"] == "running"
    assert oms_row["health"] == "healthy"
    assert oms_row["uptime_seconds"] is not None
    assert oms_row["uptime_seconds"] >= 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_happy_writes_audit(
    services_client: tuple[AsyncClient, _FakeDockerClient],
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/services/{name}/restart calls restart and audits."""
    client, fake = services_client
    response = await client.post(
        "/admin/services/oms/restart",
        headers=auth_headers,
        json={"reason": "stuck websocket"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "oms"
    assert body["restarted"] is True
    assert body["state"] == "running"

    oms = fake.containers.get("oms")
    assert oms.restart_calls, "container.restart was not invoked"
    assert oms.restart_calls[0]["timeout"] == 10

    assert _audit_count(admin_integration_dsn, "oms", "restart.service") >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_not_in_whitelist_422(
    services_client: tuple[AsyncClient, _FakeDockerClient],
    auth_headers: dict[str, str],
) -> None:
    """Names outside the whitelist return 422 (validation error)."""
    client, _ = services_client
    response = await client.post(
        "/admin/services/postgres/restart",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_missing_container_404(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Whitelisted service with no live container returns 404."""
    fake = _FakeDockerClient([], with_network=False)
    async for client in _services_client(admin_integration_dsn, fake):
        response = await client.post(
            "/admin/services/llm-gateway/restart",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_validation_error(
    services_client: tuple[AsyncClient, _FakeDockerClient],
    auth_headers: dict[str, str],
) -> None:
    """Out-of-range timeout fails Pydantic validation with 422."""
    client, _ = services_client
    response = await client.post(
        "/admin/services/oms/restart",
        headers=auth_headers,
        json={"timeout_seconds": 9999},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_services_auth_required(admin_integration_dsn: str) -> None:
    """All services endpoints reject unauthenticated requests."""
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=admin_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/services/status")).status_code == 401
            assert (await client.post("/admin/services/oms/restart", json={})).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restart_rate_limit(
    services_client: tuple[AsyncClient, _FakeDockerClient],
    auth_headers: dict[str, str],
) -> None:
    """Burst restart calls eventually return 429 (20/min write limit)."""
    client, _ = services_client
    statuses: list[int] = []
    for _ in range(22):
        resp = await client.post(
            "/admin/services/oms/restart",
            headers=auth_headers,
            json={},
        )
        statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
