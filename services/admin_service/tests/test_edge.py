"""Tests for Edge Route Registry and Cloudflare status APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from edge.canonical_routes import UNREGISTERED_INCIDENT_PORTS
from edge.config_reader import parse_cloudflared_ingress
from edge.drift_checker import compute_route_drift
from edge.canonical_routes import CANONICAL_ROUTES
from edge.service import EdgeRegistryService
from httpx import ASGITransport, AsyncClient

CANONICAL_YAML = """
tunnel: test-tunnel-id
ingress:
  - hostname: dataapi.theeyebeta.store
    service: http://127.0.0.1:7000
  - hostname: dataapiprod.theeyebeta.store
    service: http://127.0.0.1:7000
  - hostname: api.theeyebeta.store
    service: http://127.0.0.1:8000
  - hostname: admin.theeyebeta.store
    service: http://127.0.0.1:7200
  - service: http_status:404
"""

ENV_EXAMPLE = "TRUSTED_HOSTS=api.theeyebeta.store,dataapi.theeyebeta.store,127.0.0.1,localhost\n"

ENV_RUNTIME_MISSING_PROD = (
    "TRUSTED_HOSTS=api.theeyebeta.store,dataapi.theeyebeta.store,127.0.0.1,localhost\n"
)

WRONG_PORT_YAML = """
ingress:
  - hostname: dataapiprod.theeyebeta.store
    service: http://127.0.0.1:9500
  - service: http_status:404
"""

SECRET_FORBIDDEN = frozenset(
    {
        "cloudflare_api_token",
        "CLOUDFLARE_API_TOKEN",
        "token",
        "secret",
        "password",
        "api_token",
    },
)


def _walk_strings(obj: object) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_walk_strings(v))
        return out
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj:
            out.extend(_walk_strings(item))
        return out
    return [str(obj)]


def _assert_no_secrets(payload: dict[str, Any]) -> None:
    """Ensure response JSON does not expose credential values."""

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert key.lower() not in {
                    "cloudflare_api_token",
                    "jwt_secret",
                    "api_token",
                    "password",
                }
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            assert "REPLACE_ME" not in obj
            assert not obj.startswith("eyJ")  # JWT-shaped

    walk(payload)
    assert isinstance(payload.get("credentials_present"), bool)


@pytest.fixture
def edge_paths(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    dataapi = repo / "TheEyeBetaDataAPI" / "TheEyeBetaDataAPI"
    deploy = dataapi / "deploy"
    deploy.mkdir(parents=True)
    (deploy / "cloudflared-config.yml").write_text(CANONICAL_YAML, encoding="utf-8")
    (dataapi / ".env.example").write_text(ENV_EXAMPLE, encoding="utf-8")
    (dataapi / ".env").write_text(ENV_RUNTIME_MISSING_PROD, encoding="utf-8")
    host_cfg = tmp_path / "cloudflared-config.yml"
    host_cfg.write_text(CANONICAL_YAML, encoding="utf-8")
    return {
        "repo_root": repo / "TheEyeProd",
        "cloudflared_repo": deploy / "cloudflared-config.yml",
        "cloudflared_host": host_cfg,
        "dataapi_env": dataapi / ".env",
        "dataapi_example": dataapi / ".env.example",
    }


def _settings_from_paths(edge_paths: dict[str, Path], **overrides: object):
    from settings import Settings

    edge_paths["repo_root"].mkdir(parents=True, exist_ok=True)
    values = {
        "database_url": "postgresql://test:test@127.0.0.1:5432/theeyebeta",
        "edge_cloudflared_repo_config": str(edge_paths["cloudflared_repo"].resolve()),
        "edge_cloudflared_host_config": str(edge_paths["cloudflared_host"].resolve()),
        "edge_dataapi_env_path": str(edge_paths["dataapi_env"].resolve()),
        "edge_dataapi_env_example_path": str(edge_paths["dataapi_example"].resolve()),
        "repo_root": str(edge_paths["repo_root"].resolve()),
        "edge_mode": "local",
        "cloudflare_api_token": "",
        **overrides,
    }
    # model_construct avoids .env on disk overriding explicit test paths.
    return Settings.model_construct(**values)


def _integration_settings(
    admin_integration_dsn: str,
    edge_paths: dict[str, Path],
    **overrides: object,
):
    from settings import Settings

    edge_paths["repo_root"].mkdir(parents=True, exist_ok=True)
    values = {
        "database_url": admin_integration_dsn,
        "nats_url": "nats://127.0.0.1:4222",
        "redis_url": "redis://127.0.0.1:6379/15",
        "admin_password_bcrypt": "",
        "jwt_private_key": "",
        "jwt_public_key": "",
        "edge_cloudflared_repo_config": str(edge_paths["cloudflared_repo"].resolve()),
        "edge_cloudflared_host_config": str(edge_paths["cloudflared_host"].resolve()),
        "edge_dataapi_env_path": str(edge_paths["dataapi_env"].resolve()),
        "edge_dataapi_env_example_path": str(edge_paths["dataapi_example"].resolve()),
        "repo_root": str(edge_paths["repo_root"].resolve()),
        "edge_mode": "local",
        "cloudflare_api_token": "",
        **overrides,
    }
    return Settings.model_construct(**values)


@pytest.mark.unit
def test_parse_cloudflared_ingress_maps_dataapi_to_7000() -> None:
    routes = parse_cloudflared_ingress(CANONICAL_YAML)
    assert routes["dataapi.theeyebeta.store"] == "http://127.0.0.1:7000"
    assert routes["dataapiprod.theeyebeta.store"] == "http://127.0.0.1:7000"


@pytest.mark.unit
def test_port_9500_tunnel_triggers_critical_drift() -> None:
    seed = next(s for s in CANONICAL_ROUTES if s.hostname == "dataapiprod.theeyebeta.store")
    drift = compute_route_drift(
        seed,
        repo_target=None,
        host_target="http://127.0.0.1:9500",
        remote_target=None,
        port_listening=False,
        health_status="unknown",
        trusted_host_present=False,
        checked_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    assert drift.status == "critical"
    assert "9500" in " ".join(drift.messages)


@pytest.mark.unit
def test_missing_trusted_host_detected(edge_paths: dict[str, Path]) -> None:
    settings = _settings_from_paths(edge_paths)
    svc = EdgeRegistryService(settings)
    trusted = __import__("asyncio").run(svc.trusted_hosts())
    prod = next(e for e in trusted.entries if e.hostname == "dataapiprod.theeyebeta.store")
    assert prod.drift is True
    assert prod.present_in_runtime is False


@pytest.mark.unit
def test_wrong_tunnel_target_detected(edge_paths: dict[str, Path]) -> None:
    edge_paths["cloudflared_host"].write_text(WRONG_PORT_YAML, encoding="utf-8")
    edge_paths["cloudflared_repo"].write_text(WRONG_PORT_YAML, encoding="utf-8")
    settings = _settings_from_paths(edge_paths)
    svc = EdgeRegistryService(settings)
    drift = __import__("asyncio").run(svc.drift_report())
    prod = next(r for r in drift.routes if r.hostname == "dataapiprod.theeyebeta.store")
    assert prod.drift.status in {"critical", "port_mismatch", "tunnel_mismatch"}
    assert "9500" in " ".join(prod.drift.messages)


@pytest.mark.unit
def test_port_registry_excludes_9500_as_expected(edge_paths: dict[str, Path]) -> None:
    settings = _settings_from_paths(edge_paths)
    svc = EdgeRegistryService(settings)
    ports = __import__("asyncio").run(svc.port_registry())
    expected_ports = {p.port for p in ports.ports if p.expected}
    assert 7000 in expected_ports
    assert 9500 not in expected_ports
    assert 9500 in ports.unregistered_incident_ports


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cloudflare_status_redacted(edge_paths: dict[str, Path]) -> None:
    settings = _settings_from_paths(edge_paths)
    svc = EdgeRegistryService(settings)
    status = await svc.cloudflare_status()
    payload = status.model_dump(mode="json")
    _assert_no_secrets(payload)
    assert status.credentials_present is False
    assert status.mode == "local"
    assert status.dummy_mode_warning is not None
    assert "dataapi.theeyebeta.store" in status.public_hostnames


@pytest.mark.unit
@pytest.mark.asyncio
async def test_routes_map_both_dataapi_hostnames_to_7000(edge_paths: dict[str, Path]) -> None:
    settings = _settings_from_paths(edge_paths)
    svc = EdgeRegistryService(settings)
    routes = await svc.list_routes()
    for hostname in ("dataapi.theeyebeta.store", "dataapiprod.theeyebeta.store"):
        row = next(r for r in routes.routes if r.hostname == hostname)
        assert row.expected_internal_port == 7000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cloudflare_status_api_no_auth_rejected(
    admin_client: tuple[AsyncClient, Any],
) -> None:
    client, _ = admin_client
    resp = await client.get("/admin/cloudflare/status")
    assert resp.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cloudflare_status_api_redacted(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
    edge_paths: dict[str, Path],
) -> None:
    from auth import get_current_user
    from main import create_app
    from settings import get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = _integration_settings(admin_integration_dsn, edge_paths)

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test-operator"}
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/cloudflare/status", headers=auth_headers)
            assert resp.status_code == 200
            body = resp.json()
            _assert_no_secrets(body)
            assert body["credentials_present"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edge_routes_api(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
    edge_paths: dict[str, Path],
) -> None:
    from auth import get_current_user
    from httpx import ASGITransport
    from main import create_app
    from settings import get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = _integration_settings(admin_integration_dsn, edge_paths)

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test-operator"}
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/edge/routes", headers=auth_headers)
            assert resp.status_code == 200
            hostnames = {r["hostname"] for r in resp.json()["routes"]}
            assert "dataapi.theeyebeta.store" in hostnames
            assert "dataapiprod.theeyebeta.store" in hostnames


@pytest.mark.integration
@pytest.mark.asyncio
async def test_edge_drift_api(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
    edge_paths: dict[str, Path],
) -> None:
    from auth import get_current_user
    from httpx import ASGITransport
    from main import create_app
    from settings import get_settings
    from tests.conftest import _close_test_resources, _init_test_resources

    get_settings.cache_clear()
    settings = _integration_settings(admin_integration_dsn, edge_paths)

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        app.dependency_overrides[get_current_user] = lambda: {"sub": "test-operator"}
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/edge/routes/drift", headers=auth_headers)
            assert resp.status_code == 200
            assert "alerts" in resp.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unauthorized_cannot_post_cloudflare_test(
    admin_client: tuple[AsyncClient, Any],
) -> None:
    client, _ = admin_client
    resp = await client.post("/admin/cloudflare/test", json={"reason": "probe"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_control_matrix_includes_edge_categories() -> None:
    from control_matrix.registry import build_control_matrix

    categories = {e.category for e in build_control_matrix()}
    assert "Cloudflare/Edge" in categories
    assert "Edge Route Registry" in categories
    ids = {e.id for e in build_control_matrix()}
    assert "edge.route.dataapi-theeyebeta-store" in ids
    assert "edge.route.dataapiprod-theeyebeta-store" in ids
