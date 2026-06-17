"""Integration tests for admin audit API."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from zinc_schemas.admin_dto import AuditVerifyResponse

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_audit_log_happy(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/audit/log returns seeded rows."""
    client, _ = audit_admin_client
    response = await client.get("/admin/audit/log", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 100
    assert len(body["entries"]) >= 3
    actors = {e["actor"] for e in body["entries"]}
    assert "admin-api:test-operator" in actors


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_audit_log_filters(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Filters by entity_id and actor narrow results."""
    client, _ = audit_admin_client
    response = await client.get(
        "/admin/audit/log",
        headers=auth_headers,
        params={
            "entity_id": "cc0e8400-e29b-41d4-a716-446655440001",
            "actor": "admin-api:test-operator",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) >= 1
    for entry in body["entries"]:
        assert entry["entity_id"] == "cc0e8400-e29b-41d4-a716-446655440001"
        assert entry["actor"] == "admin-api:test-operator"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_audit_log_pagination(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Cursor pagination returns a second page by id."""
    client, _ = audit_admin_client
    first = await client.get(
        "/admin/audit/log",
        headers=auth_headers,
        params={"limit": 2},
    )
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["entries"]) == 2
    cursor = page1.get("next_cursor")
    assert cursor is not None

    second = await client.get(
        "/admin/audit/log",
        headers=auth_headers,
        params={"limit": 2, "cursor": cursor},
    )
    assert second.status_code == 200
    page2 = second.json()
    ids1 = {e["id"] for e in page1["entries"]}
    ids2 = {e["id"] for e in page2["entries"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_checkpoints_happy(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/audit/checkpoints returns seeded checkpoint."""
    client, _ = audit_admin_client
    response = await client.get("/admin/audit/checkpoints", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["checkpoints"]) >= 1
    assert body["checkpoints"][0]["checkpoint_id"] == "2026-05-24"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_audit_happy(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/audit/verify proxies audit-service response."""
    client, _ = audit_admin_client
    now = datetime.now(tz=UTC)
    mock_result = AuditVerifyResponse(ok=True, rows_checked=3, mismatch_at_id=None)

    with patch("api.audit.call_audit_service_verify", AsyncMock(return_value=mock_result)):
        response = await client.get(
            "/admin/audit/verify",
            headers=auth_headers,
            params={
                "from": (now - timedelta(days=1)).isoformat(),
                "to": now.isoformat(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["rows_checked"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_invalid_range_returns_422(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """``to`` before ``from`` yields 422."""
    client, _ = audit_admin_client
    now = datetime.now(tz=UTC)
    response = await client.get(
        "/admin/audit/verify",
        headers=auth_headers,
        params={"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_auth_required(audit_integration_dsn: str) -> None:
    """Audit endpoints require authentication."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # noqa: E402
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(database_url=audit_integration_dsn)

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/audit/log")).status_code == 401
            assert (await client.get("/admin/audit/checkpoints")).status_code == 401
            now = datetime.now(tz=UTC).isoformat()
            assert (
                await client.get(
                    "/admin/audit/verify",
                    params={"from": now, "to": now},
                )
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_rate_limit(
    audit_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Default 100/min rate limit returns 429 on burst reads."""
    client, _ = audit_admin_client
    statuses: list[int] = []
    for _ in range(105):
        response = await client.get("/admin/audit/log", headers=auth_headers)
        statuses.append(response.status_code)
    assert 200 in statuses
    assert 429 in statuses
