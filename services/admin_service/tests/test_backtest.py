"""Integration tests for admin backtest API."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

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

SUCCEEDED_RUN_ID = "cc111111-1111-1111-1111-111111111111"
RUNNING_RUN_ID = "cc222222-2222-2222-2222-222222222222"
NEW_RUN_ID = "cc333333-3333-3333-3333-333333333333"
STRATEGY_ID = "momentum-v1"


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


class _StubResponse:
    """Minimal httpx.Response replacement for the engine proxy tests."""

    def __init__(self, status_code: int, payload: dict[str, Any] | str) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        if isinstance(self._payload, str):
            raise ValueError("non-JSON response")
        return self._payload

    @property
    def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else ""


def _stub_client_factory(
    *,
    post: _StubResponse | None = None,
    get: _StubResponse | None = None,
    capture: list[tuple[str, str, dict[str, Any] | None]] | None = None,
) -> type:
    """Build an ``httpx.AsyncClient`` replacement returning canned responses."""

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> _StubResponse:
            if capture is not None:
                capture.append(("POST", url, json))
            assert post is not None, "POST stub not configured"
            return post

        async def get(self, url: str) -> _StubResponse:
            if capture is not None:
                capture.append(("GET", url, None))
            assert get is not None, "GET stub not configured"
            return get

    return _StubClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_recent_happy(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/backtest returns seeded runs newest first."""
    client, _ = backtest_admin_client
    response = await client.get("/admin/backtest", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 50
    ids = [row["id"] for row in body["runs"]]
    assert SUCCEEDED_RUN_ID in ids
    assert RUNNING_RUN_ID in ids
    # RUNNING_RUN_ID started 2h ago, SUCCEEDED_RUN_ID started 6h ago.
    assert ids.index(RUNNING_RUN_ID) < ids.index(SUCCEEDED_RUN_ID)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_backtest_happy(
    backtest_admin_client: tuple[AsyncClient, object],
    backtest_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/backtest forwards to engine and audit logs."""
    client, _ = backtest_admin_client
    captured: list[tuple[str, str, dict[str, Any] | None]] = []
    stub_post = _StubResponse(
        200,
        {"backtest_run_id": NEW_RUN_ID, "status": "running"},
    )
    stub_cls = _stub_client_factory(post=stub_post, capture=captured)

    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.post(
            "/admin/backtest",
            headers=auth_headers,
            json={
                "strategy_id": STRATEGY_ID,
                "start_date": "2024-07-01",
                "end_date": "2024-09-30",
                "universe": "sp500",
                "walk_forward": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["backtest_run_id"] == NEW_RUN_ID
    assert body["status"] == "running"

    assert captured, "engine was not called"
    method, url, payload = captured[0]
    assert method == "POST"
    assert url.endswith("/backtest/run")
    assert payload is not None
    assert payload["strategy_id"] == STRATEGY_ID
    assert payload["walk_forward"] is True

    assert _audit_count(backtest_integration_dsn, NEW_RUN_ID, "start.backtest") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_backtest_validation_local(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Reversed dates fail locally with 422 and never hit the engine."""
    client, _ = backtest_admin_client
    stub_cls = _stub_client_factory()
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.post(
            "/admin/backtest",
            headers=auth_headers,
            json={
                "strategy_id": STRATEGY_ID,
                "start_date": "2024-09-30",
                "end_date": "2024-07-01",
            },
        )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_backtest_engine_400_maps_to_422(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Engine 400 (validation error) is mapped to admin-side 422."""
    client, _ = backtest_admin_client
    stub_post = _StubResponse(400, "start_date must be <= end_date")
    stub_cls = _stub_client_factory(post=stub_post)
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.post(
            "/admin/backtest",
            headers=auth_headers,
            json={
                "strategy_id": STRATEGY_ID,
                "start_date": "2024-07-01",
                "end_date": "2024-09-30",
            },
        )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_results_happy(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/backtest/{id}/results forwards engine response."""
    client, _ = backtest_admin_client
    payload = {
        "backtest_run_id": SUCCEEDED_RUN_ID,
        "status": "succeeded",
        "metrics": {"sharpe": 1.42, "max_dd": -0.08},
        "result_blob_uri": "s3://theeyebeta-backtest/cc111111.parquet",
    }
    captured: list[tuple[str, str, dict[str, Any] | None]] = []
    stub_cls = _stub_client_factory(
        get=_StubResponse(200, payload),
        capture=captured,
    )
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.get(
            f"/admin/backtest/{SUCCEEDED_RUN_ID}/results",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["backtest_run_id"] == SUCCEEDED_RUN_ID
    assert body["metrics"]["sharpe"] == pytest.approx(1.42)
    assert body["result_blob_uri"] == payload["result_blob_uri"]

    assert captured and captured[0][1].endswith(f"/backtest/{SUCCEEDED_RUN_ID}/results")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_results_engine_404(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Engine 404 surfaces as 404 to the operator."""
    client, _ = backtest_admin_client
    stub_cls = _stub_client_factory(get=_StubResponse(404, "backtest run not found"))
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.get(
            f"/admin/backtest/{SUCCEEDED_RUN_ID}/results",
            headers=auth_headers,
        )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_results_engine_409(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Engine 409 (still running) surfaces as 409."""
    client, _ = backtest_admin_client
    stub_cls = _stub_client_factory(
        get=_StubResponse(409, "backtest not complete (status=running)"),
    )
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        response = await client.get(
            f"/admin/backtest/{RUNNING_RUN_ID}/results",
            headers=auth_headers,
        )
    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backtest_auth_required(backtest_integration_dsn: str) -> None:
    """All backtest endpoints reject unauthenticated requests."""
    from httpx import ASGITransport  # noqa: PLC0415

    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=backtest_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/backtest")).status_code == 401
            assert (
                await client.post(
                    "/admin/backtest",
                    json={
                        "strategy_id": STRATEGY_ID,
                        "start_date": "2024-07-01",
                        "end_date": "2024-09-30",
                    },
                )
            ).status_code == 401
            assert (
                await client.get(f"/admin/backtest/{SUCCEEDED_RUN_ID}/results")
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_start_backtest_rate_limit(
    backtest_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Burst start calls eventually return 429 (20/min write limit)."""
    client, _ = backtest_admin_client
    stub_post = _StubResponse(
        200,
        {"backtest_run_id": NEW_RUN_ID, "status": "running"},
    )
    stub_cls = _stub_client_factory(post=stub_post)

    statuses: list[int] = []
    with patch("api.backtest.httpx.AsyncClient", stub_cls):
        for _ in range(22):
            resp = await client.post(
                "/admin/backtest",
                headers=auth_headers,
                json={
                    "strategy_id": STRATEGY_ID,
                    "start_date": "2024-07-01",
                    "end_date": "2024-09-30",
                },
            )
            statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
