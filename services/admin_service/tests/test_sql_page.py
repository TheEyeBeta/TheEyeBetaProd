"""Integration tests for ``/admin/sql`` (page + fragments).

Reuses the existing ``seed_sql.sql`` sandbox table seeded by the JSON-SQL
router suite.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest_sqlpage",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)
_normalize_psycopg_dsn = _admin_conf._normalize_psycopg_dsn


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


# ---------------------------------------------------------------- Page render


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_page_renders_editor_and_modes(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/sql`` renders the textarea, both radio modes, Run button."""
    client, _ = sql_admin_client
    response = await client.get("/admin/sql", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'data-page="sql"' in body
    assert 'name="statement"' in body
    assert 'name="parameters"' in body
    # Both mode radios and the confirm phrase exposed for client JS.
    assert 'data-test-id="sql-mode-read"' in body
    assert 'data-test-id="sql-mode-write"' in body
    assert 'data-confirm-phrase="I UNDERSTAND"' in body
    # CodeMirror CDN includes.
    assert "codemirror.min.js" in body
    assert "mode/sql/sql.min.js" in body
    assert "codemirror.min.css" in body
    # Result pane placeholder.
    assert 'data-test-id="sql-result"' in body


# ---------------------------------------------------------------- Fragment: query


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_query_fragment_returns_table(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Successful SELECT renders the result table partial with rows."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/query",
        headers=auth_headers,
        data={
            "statement": ("SELECT id, label, value FROM theeyebeta.admin_sql_sandbox ORDER BY id"),
            "parameters": "",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-test-id="sql-query-result"' in body
    assert 'data-row-count="3"' in body
    assert "alpha" in body and "bravo" in body and "charlie" in body
    # Empty parameters → ``[]`` decode (no error block).
    assert 'data-test-id="sql-error"' not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_query_fragment_with_parameters(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Bind parameters are decoded from the JSON form field."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/query",
        headers=auth_headers,
        data={
            "statement": ("SELECT label FROM theeyebeta.admin_sql_sandbox WHERE id = $1"),
            "parameters": "[2]",
        },
    )
    assert response.status_code == 200
    assert 'data-row-count="1"' in response.text
    assert "bravo" in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_query_fragment_rejects_non_select(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    sql_integration_dsn: str,
) -> None:
    """A DML statement on the query fragment renders the error card."""
    _reset_sandbox(sql_integration_dsn)
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/query",
        headers=auth_headers,
        data={
            "statement": "DELETE FROM theeyebeta.admin_sql_sandbox WHERE id = 1",
            "parameters": "",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="sql-error"' in body
    assert 'data-status-code="422"' in body
    # Sandbox row was not touched.
    assert _sandbox_value(sql_integration_dsn, 1) == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_query_fragment_rejects_bad_parameters_json(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Malformed JSON in ``parameters`` returns the error card."""
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/query",
        headers=auth_headers,
        data={
            "statement": "SELECT 1",
            "parameters": "{not-json}",
        },
    )
    assert response.status_code == 200
    assert 'data-test-id="sql-error"' in response.text
    assert "invalid JSON" in response.text


# ---------------------------------------------------------------- Fragment: confirm


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_confirm_modal_mints_uuid7(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The confirmation modal renders with a fresh UUIDv7 each time."""
    client, _ = sql_admin_client
    response = await client.get("/admin/sql/fragments/confirm", headers=auth_headers)
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="sql-confirm-modal"' in body
    assert 'data-confirm-phrase="I UNDERSTAND"' in body
    assert 'name="confirm_phrase"' in body
    # Extract idempotency_key data-attr and validate it's a v7 UUID.
    marker = 'data-idempotency-key="'
    start = body.find(marker) + len(marker)
    end = body.find('"', start)
    key = body[start:end]
    parsed = uuid.UUID(key)
    assert parsed.version == 7

    # A second request returns a different key.
    response2 = await client.get("/admin/sql/fragments/confirm", headers=auth_headers)
    start = response2.text.find(marker) + len(marker)
    end = response2.text.find('"', start)
    assert response2.text[start:end] != key


# ---------------------------------------------------------------- Fragment: execute


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_execute_fragment_writes_and_audits(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    sql_integration_dsn: str,
) -> None:
    """A confirmed write updates the table and writes the audit row."""
    _reset_sandbox(sql_integration_dsn)
    client, _ = sql_admin_client
    idem = "0190a000-7000-7000-8000-000000000001"  # any valid UUID
    response = await client.post(
        "/admin/sql/fragments/execute",
        headers=auth_headers,
        data={
            "statement": ("UPDATE theeyebeta.admin_sql_sandbox SET value = 99 WHERE id = 1"),
            "parameters": "",
            "confirm_phrase": "I UNDERSTAND",
            "idempotency_key": idem,
        },
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="sql-execute-result"' in body
    assert 'data-rows-affected="1"' in body
    assert response.headers.get("HX-Trigger", "").startswith("{")
    assert "flash" in response.headers["HX-Trigger"]
    assert _sandbox_value(sql_integration_dsn, 1) == 99
    assert _audit_count(sql_integration_dsn, idem) == 1
    _reset_sandbox(sql_integration_dsn)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_execute_fragment_rejects_wrong_phrase(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    sql_integration_dsn: str,
) -> None:
    """A mismatched confirm phrase short-circuits before any DB call."""
    _reset_sandbox(sql_integration_dsn)
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/execute",
        headers=auth_headers,
        data={
            "statement": ("UPDATE theeyebeta.admin_sql_sandbox SET value = 99 WHERE id = 1"),
            "parameters": "",
            "confirm_phrase": "yes please",
            "idempotency_key": "0190a000-7000-7000-8000-000000000002",
        },
    )
    assert response.status_code == 200
    assert 'data-test-id="sql-error"' in response.text
    assert "Confirmation phrase mismatch" in response.text
    assert _sandbox_value(sql_integration_dsn, 1) == 10
    assert _audit_count(sql_integration_dsn, "0190a000-7000-7000-8000-000000000002") == 0
    _reset_sandbox(sql_integration_dsn)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_execute_fragment_rejects_protected_table(
    sql_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    sql_integration_dsn: str,
) -> None:
    """Statements touching ``audit_log`` are rejected by ``validate_execute``."""
    _reset_sandbox(sql_integration_dsn)
    client, _ = sql_admin_client
    response = await client.post(
        "/admin/sql/fragments/execute",
        headers=auth_headers,
        data={
            "statement": "DELETE FROM theeyebeta.audit_log WHERE id = 1",
            "parameters": "",
            "confirm_phrase": "I UNDERSTAND",
            "idempotency_key": "0190a000-7000-7000-8000-000000000003",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="sql-error"' in body
    assert "audit_log" in body
    _reset_sandbox(sql_integration_dsn)


# ---------------------------------------------------------------- Auth gate


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sql_page_requires_auth(
    sql_integration_dsn: str,
) -> None:
    """All SQL page routes are JWT-gated."""
    from conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(database_url=sql_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/sql")
            query = await anon.post(
                "/admin/sql/fragments/query",
                data={"statement": "SELECT 1", "parameters": ""},
            )
            confirm = await anon.get("/admin/sql/fragments/confirm")
            execute = await anon.post(
                "/admin/sql/fragments/execute",
                data={
                    "statement": "SELECT 1",
                    "parameters": "",
                    "confirm_phrase": "I UNDERSTAND",
                    "idempotency_key": "0190a000-7000-7000-8000-0000000000aa",
                },
            )
    assert page.status_code == 401
    assert query.status_code == 401
    assert confirm.status_code == 401
    assert execute.status_code == 401
