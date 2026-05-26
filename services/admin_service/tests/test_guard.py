"""Integration tests for admin guard violations API."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
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


def _pending_violation_id(dsn: str, agent_id: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT id
              FROM theeyebeta.guard_violations
             WHERE agent_id = %s
               AND resolved = false
             ORDER BY id ASC
             LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
    assert row is not None, f"no unresolved violations for {agent_id}"
    return int(row[0])


def _resolved_violation_id(dsn: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT id
              FROM theeyebeta.guard_violations
             WHERE resolved = true
             ORDER BY id ASC
             LIMIT 1
            """,
        ).fetchone()
    assert row is not None, "no resolved violations seeded"
    return int(row[0])


def _reset_seed(dsn: str) -> None:
    """Reset all violations to unresolved + clear admin audit rows for retries."""
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(
            """
            UPDATE theeyebeta.guard_violations
               SET resolved = false,
                   resolved_by = NULL,
                   resolved_at = NULL,
                   resolution_note = NULL
             WHERE resolved_by IS NULL OR resolved_by LIKE 'admin-api:%'
            """,
        )
        conn.execute(
            """
            DELETE FROM theeyebeta.audit_log
             WHERE action = 'resolve.guard_violation'
            """,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_violations_happy(
    guard_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/guard/violations returns seeded rows newest first."""
    client, _ = guard_admin_client
    response = await client.get("/admin/guard/violations", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100
    assert len(body["violations"]) >= 3
    ids = [row["id"] for row in body["violations"]]
    assert ids == sorted(ids, reverse=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_violations_filters(
    guard_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Agent / severity / unresolved_only filters narrow the result set."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/guard/violations",
        params={
            "agent_id": "macro-lead",
            "severity": "high",
            "unresolved_only": "true",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["violations"]) >= 1
    for row in body["violations"]:
        assert row["agent_id"] == "macro-lead"
        assert row["severity"] == "high"
        assert row["resolved"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_violations_invalid_severity(
    guard_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Unknown severity yields 422."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/guard/violations",
        params={"severity": "bogus"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_violation_happy(
    guard_admin_client: tuple[AsyncClient, object],
    guard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST resolve flips the row and writes an audit entry."""
    _reset_seed(guard_integration_dsn)
    client, _ = guard_admin_client
    violation_id = _pending_violation_id(guard_integration_dsn, "technical-analyst")

    response = await client.post(
        f"/admin/guard/violations/{violation_id}/resolve",
        headers=auth_headers,
        json={"note": "false positive"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == violation_id
    assert body["resolved"] is True
    assert body["resolved_by"] == "admin-api:test-operator"
    assert body["resolution_note"] == "false positive"

    assert (
        _audit_count(
            guard_integration_dsn,
            str(violation_id),
            "resolve.guard_violation",
        )
        == 1
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_violation_not_found(
    guard_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing id returns 404."""
    client, _ = guard_admin_client
    response = await client.post(
        "/admin/guard/violations/999999/resolve",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_violation_conflict(
    guard_admin_client: tuple[AsyncClient, object],
    guard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Resolving an already-resolved violation returns 409."""
    client, _ = guard_admin_client
    resolved_id = _resolved_violation_id(guard_integration_dsn)
    response = await client.post(
        f"/admin/guard/violations/{resolved_id}/resolve",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_validation_error(
    guard_admin_client: tuple[AsyncClient, object],
    guard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Note longer than the 2000-char cap returns 422."""
    client, _ = guard_admin_client
    violation_id = _pending_violation_id(guard_integration_dsn, "macro-lead")
    response = await client.post(
        f"/admin/guard/violations/{violation_id}/resolve",
        headers=auth_headers,
        json={"note": "x" * 2001},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_guard_auth_required(guard_integration_dsn: str) -> None:
    """All guard endpoints reject unauthenticated requests with 401."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=guard_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/guard/violations")).status_code == 401
            assert (
                await client.post(
                    "/admin/guard/violations/1/resolve",
                    json={},
                )
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_rate_limit(
    guard_admin_client: tuple[AsyncClient, object],
    guard_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Burst resolve calls eventually return 429 (20/min write limit)."""
    client, _ = guard_admin_client
    statuses: list[int] = []
    for _ in range(22):
        _reset_seed(guard_integration_dsn)
        violation_id = _pending_violation_id(guard_integration_dsn, "technical-analyst")
        resp = await client.post(
            f"/admin/guard/violations/{violation_id}/resolve",
            headers=auth_headers,
            json={},
        )
        statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
