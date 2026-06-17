"""Integration tests for admin SQL router."""

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


def _audit_count(dsn: str, idempotency_key: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s AND action = 'execute.sql'
            """,
            (idempotency_key,),
        ).fetchone()
    return int(row[0]) if row else 0


def _sandbox_value(dsn: str, sandbox_id: int) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            "SELECT value FROM theeyebeta.admin_sql_sandbox WHERE id = %s",
            (sandbox_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _reset_sandbox(dsn: str) -> None:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(
            """
            UPDATE theeyebeta.admin_sql_sandbox
               SET value = CASE id
                            WHEN 1 THEN 10
                            WHEN 2 THEN 20
                            WHEN 3 THEN 30
                          END
            """,
        )
        conn.execute(
            "DELETE FROM theeyebeta.audit_log WHERE action = 'execute.sql'",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_happy(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/sql/query returns rows + columns."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/query",
        headers=auth_headers,
        json={
            "statement": ("SELECT id, label, value FROM theeyebeta.admin_sql_sandbox ORDER BY id"),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["id", "label", "value"]
    assert body["row_count"] == 3
    assert body["rows"][0] == [1, "alpha", 10]
    assert body["truncated"] is False
    assert body["elapsed_ms"] >= 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_with_parameters(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Parametrized SELECT works with bound parameters."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/query",
        headers=auth_headers,
        json={
            "statement": ("SELECT label FROM theeyebeta.admin_sql_sandbox WHERE id = $1"),
            "parameters": [2],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == [["bravo"]]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_rejects_dml(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """DML/DDL keywords trip the parse guard with 422."""
    client, _ = sql_admin_client
    bad = [
        "DELETE FROM theeyebeta.admin_sql_sandbox",
        "UPDATE theeyebeta.admin_sql_sandbox SET value = 0",
        "INSERT INTO theeyebeta.admin_sql_sandbox (id, label) VALUES (4, 'd')",
        "DROP TABLE theeyebeta.admin_sql_sandbox",
        "TRUNCATE theeyebeta.admin_sql_sandbox",
        "ALTER TABLE theeyebeta.admin_sql_sandbox ADD COLUMN x int",
        "SELECT 1; SELECT 2",
        "",
    ]
    for stmt in bad:
        response = await client.post(
            "/admin/sql/query",
            headers=auth_headers,
            json={"statement": stmt},
        )
        assert response.status_code == 422, stmt


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_postgres_error(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """A bad column name surfaces as 422 (Postgres error)."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/query",
        headers=auth_headers,
        json={
            "statement": ("SELECT no_such_column FROM theeyebeta.admin_sql_sandbox"),
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_happy_writes_audit(
    sql_admin_client: tuple[AsyncClient, object],
    sql_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST /admin/sql/execute updates rows and writes an audit entry."""
    _reset_sandbox(sql_integration_dsn)
    client, _ = sql_admin_client
    headers = {
        **auth_headers,
        "X-Confirm": "true",
        "X-Idempotency-Key": "test-execute-1",
    }
    response = await client.post(
        "/admin/sql/execute",
        headers=headers,
        json={
            "statement": ("UPDATE theeyebeta.admin_sql_sandbox SET value = $1 WHERE id = $2"),
            "parameters": [99, 1],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["command_tag"].startswith("UPDATE")
    assert body["rows_affected"] == 1
    assert body["idempotency_key"] == "test-execute-1"

    assert _sandbox_value(sql_integration_dsn, 1) == 99
    assert _audit_count(sql_integration_dsn, "test-execute-1") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_requires_confirm_header(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing X-Confirm header → 422."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/execute",
        headers={**auth_headers, "X-Idempotency-Key": "k1"},
        json={
            "statement": "UPDATE theeyebeta.admin_sql_sandbox SET value = 0",
        },
    )
    assert response.status_code == 422
    assert "X-Confirm" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_requires_idempotency_key(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing X-Idempotency-Key header → 422."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/execute",
        headers={**auth_headers, "X-Confirm": "true"},
        json={
            "statement": "UPDATE theeyebeta.admin_sql_sandbox SET value = 0",
        },
    )
    assert response.status_code == 422
    assert "Idempotency-Key" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_rejects_protected_tables(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Statements that touch audit_log / proposals are blocked at parse time."""
    client, _ = sql_admin_client
    headers = {
        **auth_headers,
        "X-Confirm": "true",
        "X-Idempotency-Key": "blocked-1",
    }
    response = await client.post(
        "/admin/sql/execute",
        headers=headers,
        json={
            "statement": ("DELETE FROM theeyebeta.audit_log WHERE entity_id = '1'"),
        },
    )
    assert response.status_code == 422

    response = await client.post(
        "/admin/sql/execute",
        headers=headers,
        json={
            "statement": "UPDATE theeyebeta.proposals SET status = 'rejected'",
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_auth_required(sql_integration_dsn: str) -> None:
    """Both endpoints reject unauthenticated requests with 401."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=sql_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (
                await client.post("/admin/sql/query", json={"statement": "SELECT 1"})
            ).status_code == 401
            assert (
                await client.post(
                    "/admin/sql/execute",
                    headers={
                        "X-Confirm": "true",
                        "X-Idempotency-Key": "x",
                    },
                    json={
                        "statement": "UPDATE theeyebeta.admin_sql_sandbox SET value = 0",
                    },
                )
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_rate_limit(
    sql_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Burst /query calls eventually return 429 (20/min limit)."""
    client, _ = sql_admin_client
    statuses: list[int] = []
    for _ in range(22):
        resp = await client.post(
            "/admin/sql/query",
            headers=auth_headers,
            json={"statement": "SELECT 1"},
        )
        statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
