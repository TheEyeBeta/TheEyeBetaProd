"""Integration tests for ``/admin/violations`` (page + fragments).

Uses the existing ``seed_guard.sql`` fixture (3 violations: TA-low pending,
macro-high pending, TA-medium already-resolved).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

TA_AGENT = "technical-analyst"
MACRO_AGENT = "macro-lead"


def _list_violations(dsn: str) -> list[dict[str, Any]]:
    """Return the seeded guard_violations rows ordered by id ascending."""
    with (
        psycopg.connect(dsn) as conn,  # type: ignore[no-untyped-call]
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            SELECT id, agent_id, severity, resolved
              FROM theeyebeta.guard_violations
             ORDER BY id ASC
            """,
        )
        rows = cur.fetchall()
    return [{"id": r[0], "agent_id": r[1], "severity": r[2], "resolved": r[3]} for r in rows]


# ---------------------------------------------------------------- Page render


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_page_renders_unresolved_by_default(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    guard_integration_dsn: str,
) -> None:
    """``GET /admin/violations`` renders only the two unresolved rows by default."""
    client, _ = guard_admin_client
    response = await client.get("/admin/violations", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # Shell
    assert "Guard violations" in body
    assert 'aria-current="page"' in body
    assert 'id="violations-filter-form"' in body
    assert 'name="agent_id"' in body
    assert 'name="severity"' in body
    assert 'name="unresolved_only"' in body
    # Default state: unresolved_only checkbox is checked. We assert on the
    # filtered row set rather than the exact ``checked`` attribute placement
    # since Jinja whitespace varies.
    # Only the two unresolved rows visible.
    assert 'data-test-id="violations-table"' in body
    assert 'data-row-count="2"' in body
    assert "schema" in body  # TA-low
    assert "mandate_boundary" in body  # macro-high
    # The already-resolved row is filtered out.
    assert "confidence_range" not in body
    # Severity badges
    assert "severity-low" in body
    assert "severity-high" in body

    # Confirm seed shape (sanity-check fixture).
    rows = _list_violations(guard_integration_dsn)
    assert len(rows) == 3
    assert sum(1 for r in rows if not r["resolved"]) == 2


# ---------------------------------------------------------------- Fragment: list


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_list_fragment_returns_partial(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The list fragment returns just the table (no ``<html>``)."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/violations/fragments/list",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
    assert 'data-test-id="violations-table"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_list_includes_resolved_when_filter_off(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``unresolved_only=false`` returns all 3 seeded violations."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/violations/fragments/list?unresolved_only=false",
        headers=auth_headers,
    )
    body = response.text
    assert 'data-row-count="3"' in body
    assert "confidence_range" in body  # resolved row included


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_list_filters_by_severity(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Severity filter narrows the result set."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/violations/fragments/list?severity=high&unresolved_only=false",
        headers=auth_headers,
    )
    body = response.text
    assert 'data-row-count="1"' in body
    assert MACRO_AGENT in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_list_filters_by_agent_id(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Agent id filter narrows the result set."""
    client, _ = guard_admin_client
    response = await client.get(
        f"/admin/violations/fragments/list?agent_id={TA_AGENT}&unresolved_only=false",
        headers=auth_headers,
    )
    body = response.text
    # TA has 2 violations (one pending low + one resolved medium).
    assert 'data-row-count="2"' in body
    assert MACRO_AGENT not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_list_rejects_invalid_severity(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """An invalid ``severity`` filter is rejected with 422."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/violations/fragments/list?severity=bogus",
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- Resolve modal


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violation_resolve_modal_renders_for_pending(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    guard_integration_dsn: str,
) -> None:
    """The resolve-modal fragment renders the form for a pending violation."""
    client, _ = guard_admin_client
    rows = _list_violations(guard_integration_dsn)
    pending = next(r for r in rows if not r["resolved"])

    response = await client.get(
        f"/admin/violations/fragments/{pending['id']}/resolve-modal",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="violation-resolve-modal"' in body
    assert f'data-violation-id="{pending["id"]}"' in body
    assert f'hx-post="/admin/violations/fragments/{pending["id"]}/resolve"' in body
    assert 'name="note"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violation_resolve_modal_409_for_resolved(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    guard_integration_dsn: str,
) -> None:
    """Already-resolved violation → 409 from the modal endpoint."""
    client, _ = guard_admin_client
    rows = _list_violations(guard_integration_dsn)
    resolved = next(r for r in rows if r["resolved"])

    response = await client.get(
        f"/admin/violations/fragments/{resolved['id']}/resolve-modal",
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violation_resolve_modal_404_for_unknown(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Unknown violation id → 404."""
    client, _ = guard_admin_client
    response = await client.get(
        "/admin/violations/fragments/9999999/resolve-modal",
        headers=auth_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------- Resolve action


def _audit_row_count(dsn: str, violation_id: int) -> int:
    """Return the number of ``resolve.guard_violation`` audit rows for ``id``."""
    with (
        psycopg.connect(dsn) as conn,  # type: ignore[no-untyped-call]
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE action = 'resolve.guard_violation'
               AND entity_id = %s
            """,
            (str(violation_id),),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violation_resolve_marks_row_and_writes_audit(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    guard_integration_dsn: str,
) -> None:
    """Submitting the resolve form updates the row, audits, and returns updated HTML."""
    client, _ = guard_admin_client
    rows = _list_violations(guard_integration_dsn)
    # Pick the lowest-id pending row so the test is deterministic across reruns.
    pending = next(
        (r for r in rows if not r["resolved"]),
        None,
    )
    assert pending is not None, "fixture must contain at least one pending violation"

    pre_audit = _audit_row_count(guard_integration_dsn, pending["id"])

    response = await client.post(
        f"/admin/violations/fragments/{pending['id']}/resolve",
        headers=auth_headers,
        data={"note": "  ack — false positive  "},
    )
    assert response.status_code == 200
    body = response.text
    # Updated row HTML.
    assert f'id="violation-row-{pending["id"]}"' in body
    assert 'data-resolved="true"' in body
    assert "resolved" in body
    assert "ack — false positive" in body
    # Toast event header.
    assert "HX-Trigger" in response.headers
    assert "Violation" in response.headers["HX-Trigger"]
    # Audit log written.
    assert _audit_row_count(guard_integration_dsn, pending["id"]) == pre_audit + 1
    # DB state mutated.
    db_rows = _list_violations(guard_integration_dsn)
    db_row = next(r for r in db_rows if r["id"] == pending["id"])
    assert db_row["resolved"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violation_resolve_409_when_already_resolved(
    guard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    guard_integration_dsn: str,
) -> None:
    """Re-resolving an already-resolved row → 409 (delegated to impl)."""
    client, _ = guard_admin_client
    rows = _list_violations(guard_integration_dsn)
    resolved = next(r for r in rows if r["resolved"])
    response = await client.post(
        f"/admin/violations/fragments/{resolved['id']}/resolve",
        headers=auth_headers,
        data={"note": ""},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------- Auth gate


@pytest.mark.integration
@pytest.mark.asyncio
async def test_violations_page_requires_auth(
    guard_integration_dsn: str,
) -> None:
    """All violations routes are JWT-gated."""
    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(database_url=guard_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/violations")
            list_frag = await anon.get("/admin/violations/fragments/list")
            modal_frag = await anon.get("/admin/violations/fragments/1/resolve-modal")
            post = await anon.post(
                "/admin/violations/fragments/1/resolve",
                data={"note": ""},
            )
    assert page.status_code == 401
    assert list_frag.status_code == 401
    assert modal_frag.status_code == 401
    assert post.status_code == 401
