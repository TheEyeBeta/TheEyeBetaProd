"""Integration tests for admin agents API."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import psycopg
import pytest
from httpx import AsyncClient

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

AGENT_ID = "technical-analyst"
SNAPSHOT_ID = "11111111-1111-1111-1111-111111111111"


def _audit_count(dsn: str, agent_id: str, action: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s AND action = %s
            """,
            (agent_id, action),
        ).fetchone()
    return int(row[0]) if row else 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_agents_happy(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/agents returns seeded agents with run aggregates."""
    client, _ = agents_admin_client
    response = await client.get("/admin/agents", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["agents"]}
    assert AGENT_ID in ids
    technical = next(row for row in body["agents"] if row["id"] == AGENT_ID)
    assert technical["model_default"] == "gpt-4o-mini"
    assert technical["runs_7d"] >= 5
    # 4 succeeded out of 5 → 0.8.
    assert technical["success_rate_7d"] == pytest.approx(0.8, rel=1e-3)
    assert technical["last_run_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_agent_runs_happy(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/agents/{id}/runs returns rows newest first with default limit."""
    client, _ = agents_admin_client
    response = await client.get(
        f"/admin/agents/{AGENT_ID}/runs",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == AGENT_ID
    assert body["limit"] == 50
    assert len(body["runs"]) >= 5
    # Newest first.
    timestamps = [row["started_at"] for row in body["runs"]]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_agent_runs_unknown_agent_404(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Unknown agent id yields 404."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents/does-not-exist/runs",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_constitution_happy(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/agents/{id}/constitution returns markdown content."""
    client, _ = agents_admin_client
    response = await client.get(
        f"/admin/agents/{AGENT_ID}/constitution",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == AGENT_ID
    assert body["constitution_path"].endswith("technical-analyst.md")
    assert "# Role" in body["content"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_constitution_unknown_agent_404(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Constitution lookup on missing agent returns 404."""
    client, _ = agents_admin_client
    response = await client.get(
        "/admin/agents/missing-agent/constitution",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_agent_happy_writes_audit(
    agents_admin_client: tuple[AsyncClient, object],
    agents_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/agents/{id}/run forwards to runtime and audit logs."""
    client, _ = agents_admin_client

    runtime_payload = {
        "run_id": "deadbeef-0000-0000-0000-000000000001",
        "snapshot_id": SNAPSHOT_ID,
        "decisions": [],
        "decision_rows": [],
        "cost_usd": 0.42,
        "market_stance": "neutral",
        "regime_call": "expansion",
        "kind": "run",
    }

    class _StubResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return runtime_payload

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._captured: dict[str, object] = {}

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> _StubResponse:
            self._captured["url"] = url
            self._captured["json"] = json
            captured.append((url, json))
            return _StubResponse()

    captured: list[tuple[str, dict[str, object]]] = []

    with patch("api.agents.httpx.AsyncClient", _StubClient):
        response = await client.post(
            f"/admin/agents/{AGENT_ID}/run",
            headers=auth_headers,
            json={"snapshot_id": SNAPSHOT_ID, "kind": "run"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == runtime_payload["run_id"]
    assert body["kind"] == "run"

    assert captured, "agent-runtime was not called"
    url, payload = captured[0]
    assert url.endswith(f"/agents/{AGENT_ID}/run")
    assert payload["snapshot_id"] == SNAPSHOT_ID
    assert payload["kind"] == "run"

    assert _audit_count(agents_integration_dsn, AGENT_ID, "run.agent") >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_agent_unknown_agent_404(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Unknown agent triggers 404 before reaching agent-runtime."""
    client, _ = agents_admin_client
    with patch(
        "api.agents.httpx.AsyncClient",
        AsyncMock(side_effect=AssertionError("runtime should not be called")),
    ):
        response = await client.post(
            "/admin/agents/missing-agent/run",
            headers=auth_headers,
            json={"snapshot_id": SNAPSHOT_ID},
        )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_agent_validation_error(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing snapshot_id returns 422."""
    client, _ = agents_admin_client
    response = await client.post(
        f"/admin/agents/{AGENT_ID}/run",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agents_auth_required(agents_integration_dsn: str) -> None:
    """All agents endpoints reject unauthenticated requests."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=agents_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/agents")).status_code == 401
            assert (await client.get(f"/admin/agents/{AGENT_ID}/runs")).status_code == 401
            assert (
                await client.post(
                    f"/admin/agents/{AGENT_ID}/run",
                    json={"snapshot_id": SNAPSHOT_ID},
                )
            ).status_code == 401
            assert (await client.get(f"/admin/agents/{AGENT_ID}/constitution")).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_agent_rate_limit(
    agents_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Burst trigger calls return 429 (20/min write limit)."""
    client, _ = agents_admin_client

    runtime_payload = {
        "run_id": "deadbeef-0000-0000-0000-000000000099",
        "snapshot_id": SNAPSHOT_ID,
        "decisions": [],
        "decision_rows": [],
        "cost_usd": 0.0,
        "market_stance": "neutral",
        "regime_call": "expansion",
        "kind": "run",
    }

    class _StubResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return runtime_payload

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, *_: object, **__: object) -> _StubResponse:
            return _StubResponse()

    statuses: list[int] = []
    with patch("api.agents.httpx.AsyncClient", _StubClient):
        for _ in range(22):
            resp = await client.post(
                f"/admin/agents/{AGENT_ID}/run",
                headers=auth_headers,
                json={"snapshot_id": SNAPSHOT_ID},
            )
            statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
