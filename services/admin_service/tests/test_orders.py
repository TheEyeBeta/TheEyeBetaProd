"""Integration tests for admin orders API."""

from __future__ import annotations

import json
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

import importlib.util

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)

PENDING_ORDER_ID = _admin_conf.PENDING_ORDER_ID
PENDING_ORDER_ID_2 = _admin_conf.PENDING_ORDER_ID_2
APPROVED_ORDER_ID = _admin_conf.APPROVED_ORDER_ID
_normalize_psycopg_dsn = _admin_conf._normalize_psycopg_dsn
_run_sql_file = _admin_conf._run_sql_file

_SQL_SEED = Path(__file__).resolve().parent / "sql" / "seed_orders.sql"


def _audit_count(dsn: str, order_id: str, action: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s
               AND action = %s
            """,
            (order_id, action),
        ).fetchone()
    return int(row[0]) if row else 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_pending_happy(
    orders_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/orders/pending returns seeded pending orders."""
    client, _nats = orders_admin_client
    response = await client.get("/admin/orders/pending", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    ids = {item["id"] for item in body["orders"]}
    assert PENDING_ORDER_ID in ids
    assert PENDING_ORDER_ID_2 in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_order_happy(
    orders_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/orders/{id} returns detail for a pending order."""
    client, _ = orders_admin_client
    response = await client.get(
        f"/admin/orders/{PENDING_ORDER_ID}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == PENDING_ORDER_ID
    assert body["instrument"]["symbol"] == "AAPL"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_order_not_found(
    orders_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing order returns 404."""
    client, _ = orders_admin_client
    missing = "00000000-0000-0000-0000-000000000099"
    response = await client.get(f"/admin/orders/{missing}", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_required(orders_integration_dsn: str) -> None:
    """Endpoints reject unauthenticated requests with 401."""
    from unittest.mock import patch  # noqa: PLC0415

    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close_test_resources = _admin_conf._close_test_resources
    _init_test_resources = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=orders_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/orders/pending")).status_code == 401
            assert (await client.get(f"/admin/orders/{PENDING_ORDER_ID}")).status_code == 401
            assert (
                await client.post(f"/admin/orders/{PENDING_ORDER_ID}/approve", json={})
            ).status_code == 401
            assert (
                await client.post(
                    f"/admin/orders/{PENDING_ORDER_ID}/reject",
                    json={"rejection_reason": "no"},
                )
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_order_happy(
    orders_admin_client: tuple[AsyncClient, object],
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST approve transitions status and writes audit + NATS."""
    client, nats = orders_admin_client
    with (
        patch("api.orders.check_risk_order", AsyncMock(return_value={"approved": True})),
        patch("api.orders.check_compliance_order", AsyncMock(return_value={"approved": True})),
    ):
        response = await client.post(
            f"/admin/orders/{PENDING_ORDER_ID}/approve",
            headers={**auth_headers, "X-Confirm": "true"},
            json={"reason": "looks good", "confirm": True, "note": "looks good"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["approved_by"] == "admin-api:test-operator"

    assert _audit_count(orders_integration_dsn, PENDING_ORDER_ID, "approve.order") == 1

    subject, payload = nats.published[-1]
    assert subject == f"orders.approved.{PENDING_ORDER_ID}"
    event = json.loads(payload.decode())
    assert event["status"] == "approved"
    assert event["order_id"] == PENDING_ORDER_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_rejects_on_risk_block(
    orders_admin_client: tuple[AsyncClient, object],
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """A risk-service block auto-rejects the order instead of approving it."""
    client, nats = orders_admin_client
    _run_sql_file(orders_integration_dsn, _SQL_SEED)
    with (
        patch(
            "api.orders.check_risk_order",
            AsyncMock(return_value={"approved": False, "reason": "position_size_pct breach"}),
        ),
        patch("api.orders.check_compliance_order", AsyncMock()) as mock_compliance,
    ):
        response = await client.post(
            f"/admin/orders/{PENDING_ORDER_ID}/approve",
            headers={**auth_headers, "X-Confirm": "true"},
            json={"reason": "looks good", "confirm": True},
        )

    assert response.status_code == 422
    assert "position_size_pct" in response.json()["detail"]
    mock_compliance.assert_not_called()
    assert _audit_count(orders_integration_dsn, PENDING_ORDER_ID, "reject.order") >= 1
    assert not nats.published or nats.published[-1][0] != f"orders.approved.{PENDING_ORDER_ID}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_rejects_on_compliance_block(
    orders_admin_client: tuple[AsyncClient, object],
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """A compliance-service block auto-rejects the order even when risk approves."""
    client, _nats = orders_admin_client
    _run_sql_file(orders_integration_dsn, _SQL_SEED)
    with (
        patch("api.orders.check_risk_order", AsyncMock(return_value={"approved": True})),
        patch(
            "api.orders.check_compliance_order",
            AsyncMock(return_value={"approved": False, "reason": "legal hold active"}),
        ),
    ):
        response = await client.post(
            f"/admin/orders/{PENDING_ORDER_ID}/approve",
            headers={**auth_headers, "X-Confirm": "true"},
            json={"reason": "looks good", "confirm": True},
        )

    assert response.status_code == 422
    assert "legal hold" in response.json()["detail"]
    assert _audit_count(orders_integration_dsn, PENDING_ORDER_ID, "reject.order") >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_conflict(
    orders_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Approving a non-pending order returns 409."""
    client, _ = orders_admin_client
    response = await client.post(
        f"/admin/orders/{APPROVED_ORDER_ID}/approve",
        headers={**auth_headers, "X-Confirm": "true"},
        json={"reason": "retry", "confirm": True},
    )
    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_order_happy(
    orders_admin_client: tuple[AsyncClient, object],
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST reject stores rejection_reason in metadata and audits."""
    client, _ = orders_admin_client
    response = await client.post(
        f"/admin/orders/{PENDING_ORDER_ID_2}/reject",
        headers={**auth_headers, "X-Confirm": "true"},
        json={"rejection_reason": "risk limit exceeded", "confirm": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["metadata"]["rejection_reason"] == "risk limit exceeded"
    assert _audit_count(orders_integration_dsn, PENDING_ORDER_ID_2, "reject.order") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_validation_error(
    orders_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Reject without reason returns 422."""
    client, _ = orders_admin_client
    response = await client.post(
        f"/admin/orders/{PENDING_ORDER_ID_2}/reject",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_rate_limit(
    orders_admin_client: tuple[AsyncClient, object],
    orders_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Burst approve calls eventually return 429 (20/min write limit)."""
    client, _ = orders_admin_client
    statuses: list[int] = []
    with (
        patch("api.orders.check_risk_order", AsyncMock(return_value={"approved": True})),
        patch("api.orders.check_compliance_order", AsyncMock(return_value={"approved": True})),
    ):
        for _ in range(22):
            _run_sql_file(orders_integration_dsn, _SQL_SEED)
            response = await client.post(
                f"/admin/orders/{PENDING_ORDER_ID}/approve",
                headers={**auth_headers, "X-Confirm": "true"},
                json={"reason": "burst", "confirm": True},
            )
            statuses.append(response.status_code)
    assert 200 in statuses
    assert 429 in statuses
