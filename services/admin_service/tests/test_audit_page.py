"""Integration tests for ``/admin/audit`` (page + fragments).

Uses the existing ``seed_audit.sql`` fixture (3 audit rows + 1 checkpoint).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_page_renders_with_initial_rows(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/audit`` renders the filter form + verify form + table."""
    client, _ = audit_admin_client
    response = await client.get("/admin/audit", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text

    # Shell
    assert "Audit log" in body
    assert 'aria-current="page"' in body  # active nav

    # Verify form
    assert 'id="audit-verify-form"' in body
    assert 'hx-get="/admin/audit/fragments/verify"' in body
    assert 'name="from"' in body
    assert 'name="to"' in body

    # Filter form
    assert 'id="audit-filter-form"' in body
    assert 'hx-get="/admin/audit/fragments/log"' in body
    assert 'name="entity_id"' in body
    assert 'name="actor"' in body
    assert 'name="since"' in body
    assert 'name="limit"' in body

    # Table with the seeded rows. Other admin fixtures can share this DB, so
    # assert the seeded content rather than a global row count.
    assert 'data-test-id="audit-table"' in body
    assert "admin-api:test-operator" in body
    assert "oms" in body
    assert "admin-api:other" in body
    assert "approve.order" in body
    assert "submit.order" in body
    assert "reject.order" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_fragment_returns_partial(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The log fragment returns just the table (no ``<html>``)."""
    client, _ = audit_admin_client
    response = await client.get(
        "/admin/audit/fragments/log?limit=50",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
    assert 'data-test-id="audit-table"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_fragment_filters_by_actor(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Filtering by ``actor`` reduces the row count."""
    client, _ = audit_admin_client
    response = await client.get(
        "/admin/audit/fragments/log?actor=oms",
        headers=auth_headers,
    )
    body = response.text
    assert "submit.order" in body
    # Other actors filtered out.
    assert "admin-api:test-operator" not in body
    assert "admin-api:other" not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_fragment_pagination_cursor(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``limit=2`` returns a cursor, and ``append=true`` swaps just rows."""
    client, _ = audit_admin_client

    page_one = await client.get(
        "/admin/audit/fragments/log?limit=2",
        headers=auth_headers,
    )
    assert page_one.status_code == 200
    body_one = page_one.text
    assert 'data-row-count="2"' in body_one
    # Cursor button rendered.
    assert "Load older" in body_one
    assert "cursor=" in body_one
    # Pull the cursor out of the body.
    import re  # noqa: PLC0415

    match = re.search(r"cursor=(\d+)", body_one)
    assert match is not None
    cursor = match.group(1)

    page_two = await client.get(
        f"/admin/audit/fragments/log?append=true&cursor={cursor}&limit=2",
        headers=auth_headers,
    )
    assert page_two.status_code == 200
    body_two = page_two.text
    # No table wrapper this time — just <tr>s.
    assert 'data-test-id="audit-table"' not in body_two
    assert "<table" not in body_two
    # And the third (oldest) row is included.
    assert "audit-row-" in body_two


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_fragment_blank_filters_ignored(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Empty / whitespace filters are treated as ``None`` (returns all rows)."""
    client, _ = audit_admin_client
    response = await client.get(
        "/admin/audit/fragments/log?entity_id=&actor=  &limit=50",
        headers=auth_headers,
    )
    body = response.text
    assert 'data-test-id="audit-table"' in body
    assert "approve.order" in body
    assert "submit.order" in body
    assert "reject.order" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_fragment_clamps_limit(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """An oversized limit is clamped to ``_AUDIT_MAX_LIMIT`` (500)."""
    client, _ = audit_admin_client
    response = await client.get(
        "/admin/audit/fragments/log?limit=999999",
        headers=auth_headers,
    )
    body = response.text
    assert "page size 500" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_verify_fragment_ok(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """A successful audit-service response renders the green ``verified`` card."""
    client, _ = audit_admin_client

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"status": "OK", "first_bad_row_id": None, "rows_checked": 42}

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any] | None = None) -> _Resp:
            assert params and "from" in params and "to" in params
            return _Resp()

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.get(
            "/admin/audit/fragments/verify?from=2026-05-24T00:00&to=2026-05-25T00:00",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.text
    assert 'data-verify-ok="true"' in body
    assert "Chain OK" in body
    assert "42" in body
    # Range echoed back to the operator.
    assert "2026-05-24" in body
    assert "2026-05-25" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_verify_fragment_mismatch(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """A mismatch from audit-service renders the purple ``mismatch`` card."""
    client, _ = audit_admin_client

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "status": "MISMATCH",
                "first_bad_row_id": 17,
                "rows_checked": 99,
                "detail": "row 17 hash != expected",
            }

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any] | None = None) -> _Resp:  # noqa: ARG002
            return _Resp()

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.get(
            "/admin/audit/fragments/verify?from=2026-05-24T00:00&to=2026-05-25T00:00",
            headers=auth_headers,
        )
    body = response.text
    assert 'data-verify-ok="false"' in body
    assert "mismatch" in body.lower()
    assert "17" in body
    assert "99 rows checked" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_verify_fragment_unreachable(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Network failure → red ``error`` card, not a 5xx response."""
    client, _ = audit_admin_client

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ARG002
            import httpx  # noqa: PLC0415

            raise httpx.ConnectError("connection refused")

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.get(
            "/admin/audit/fragments/verify?from=2026-05-24T00:00&to=2026-05-25T00:00",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.text
    assert 'data-verify-ok="error"' in body
    assert "Verify failed" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_verify_fragment_rejects_inverted_range(
    audit_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``to`` before ``from`` renders an inline error without touching audit-service."""
    client, _ = audit_admin_client

    sentinel: list[bool] = []

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ARG002
            sentinel.append(True)
            raise AssertionError("audit-service should not be called for inverted range")

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.get(
            "/admin/audit/fragments/verify?from=2026-05-26T00:00&to=2026-05-24T00:00",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.text
    assert 'data-verify-ok="error"' in body
    assert "must be greater than or equal to" in body
    assert not sentinel  # the stub HTTP client was never called


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_page_requires_auth(
    audit_integration_dsn: str,
) -> None:
    """All audit page routes are JWT-gated."""
    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(
        database_url=audit_integration_dsn,
        audit_service_url="http://127.0.0.1:7110",
    )
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/audit")
            log_frag = await anon.get("/admin/audit/fragments/log")
            verify = await anon.get(
                "/admin/audit/fragments/verify?from=2026-05-24T00:00&to=2026-05-25T00:00",
            )
    assert page.status_code == 401
    assert log_frag.status_code == 401
    assert verify.status_code == 401
