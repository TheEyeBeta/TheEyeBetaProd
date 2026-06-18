"""Integration tests for the server-rendered orders page + htmx fragments.

Covers ``/admin/orders``, the rationale-expand fragment, the reject modal,
and the approve / reject row-swap endpoints.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

LONG_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440091"
SHORT_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440092"
MARKET_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440093"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_page_lists_pending_rows(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/orders`` renders one ``<tr>`` per pending order."""
    client, _ = orders_page_admin_client
    response = await client.get("/admin/orders", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text

    assert "Pending orders" in body
    assert 'id="orders-tbody"' in body
    for order_id in (LONG_ORDER_ID, SHORT_ORDER_ID, MARKET_ORDER_ID):
        assert f'id="order-row-{order_id}"' in body
        assert f'hx-post="/admin/orders/fragments/{order_id}/approve"' in body
        assert f'hx-get="/admin/orders/fragments/{order_id}/reject-modal"' in body

    # Side badges + qty formatting.
    assert ">BUY<" in body
    assert ">SELL<" in body
    assert "12.0000" in body  # long order qty
    assert "$155.50" in body  # long order limit_price
    assert "market" in body  # market order shows "market" instead of price


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_page_rationale_truncation(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Long rationale → truncated snippet + expand button. Short → no button."""
    client, _ = orders_page_admin_client
    body = (await client.get("/admin/orders", headers=auth_headers)).text

    long_row = _slice_row(body, LONG_ORDER_ID)
    assert "Persistent up-trend" in long_row
    assert "…" in long_row  # snippet truncation suffix
    assert f'hx-get="/admin/orders/fragments/{LONG_ORDER_ID}/rationale"' in long_row
    assert "Show full rationale" in long_row

    short_row = _slice_row(body, SHORT_ORDER_ID)
    assert "Hit profit target. Exit half." in short_row
    assert "Show full rationale" not in short_row

    no_rat_row = _slice_row(body, MARKET_ORDER_ID)
    assert "no rationale recorded" in no_rat_row


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_empty_state(
    admin_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """When there are no pending orders the table renders the empty-state row."""
    # Use the *admin* DSN (migrations only — no seed) so the table is empty.
    from services.admin_service.tests.conftest import (
        _admin_client_for_dsn,  # type: ignore[import-not-found]  # noqa: PLC0415
    )

    async for tup in _admin_client_for_dsn(admin_integration_dsn, auth_headers):
        client, _ = tup
        response = await client.get("/admin/orders", headers=auth_headers)
        assert response.status_code == 200
        body = response.text
        assert "Nothing pending" in body
        assert 'data-empty="true"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_rationale_fragment_returns_partial(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Rationale fragment returns only the inner block — no full <html>."""
    client, _ = orders_page_admin_client
    response = await client.get(
        f"/admin/orders/fragments/{LONG_ORDER_ID}/rationale",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
    assert 'data-test-id="rationale-expanded"' in body
    # Full rationale text (not the truncated snippet) is present.
    assert "0.75% NAV" in body
    assert "Stop at $145" in body
    # The expanded view offers a "Hide" button pointing at the snippet endpoint.
    assert f'hx-get="/admin/orders/fragments/{LONG_ORDER_ID}/rationale-snippet"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_rationale_snippet_endpoint(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """The collapse endpoint returns the truncated view with the expand button."""
    client, _ = orders_page_admin_client
    response = await client.get(
        f"/admin/orders/fragments/{LONG_ORDER_ID}/rationale-snippet",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="rationale-snippet"' in body
    # Truncated snippet, no "0.75% NAV" (that's only in the full text).
    assert "Persistent up-trend" in body
    assert "0.75% NAV" not in body
    # Expand button points back at the full rationale endpoint.
    assert f'hx-get="/admin/orders/fragments/{LONG_ORDER_ID}/rationale"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_rationale_fragment_404_for_unknown_id(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Rationale fragment returns 404 when the order doesn't exist."""
    client, _ = orders_page_admin_client
    response = await client.get(
        "/admin/orders/fragments/00000000-0000-0000-0000-000000000000/rationale",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_reject_modal_renders_form(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET reject-modal`` returns a partial with a textarea + POST form."""
    client, _ = orders_page_admin_client
    response = await client.get(
        f"/admin/orders/fragments/{LONG_ORDER_ID}/reject-modal",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-test-id="order-reject-modal"' in body
    assert f'hx-post="/admin/orders/fragments/{LONG_ORDER_ID}/reject"' in body
    assert 'name="rejection_reason"' in body
    assert "AAPL" in body  # order context displayed
    assert "BUY" in body
    assert "12.0000" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_approve_fragment_updates_row_and_audits(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    orders_page_integration_dsn: str,
) -> None:
    """Approving via the fragment endpoint flips status + audits + publishes NATS."""
    client, nats_stub = orders_page_admin_client
    response = await client.post(
        f"/admin/orders/fragments/{SHORT_ORDER_ID}/approve",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    # The response is just the updated <tr>, not the full page.
    assert "<html" not in body.lower()
    assert f'id="order-row-{SHORT_ORDER_ID}"' in body
    assert 'data-order-status="approved"' in body
    assert ">Approved<" in body

    # NATS event was published with the right subject.
    subjects = [subj for subj, _ in nats_stub.published]
    assert f"orders.approved.{SHORT_ORDER_ID}" in subjects

    # Audit row written.
    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn=orders_page_integration_dsn)
    try:
        row = await conn.fetchrow(
            """
            SELECT actor, action, entity_id, payload
              FROM theeyebeta.audit_log
             WHERE entity_id = $1 AND action = 'approve.order'
             ORDER BY id DESC LIMIT 1
            """,
            SHORT_ORDER_ID,
        )
    finally:
        await conn.close()
    assert row is not None
    assert row["actor"] == "admin-api:test-operator"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_reject_fragment_requires_reason(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """A blank ``rejection_reason`` field is rejected before any DB write."""
    client, _ = orders_page_admin_client
    response = await client.post(
        f"/admin/orders/fragments/{MARKET_ORDER_ID}/reject",
        headers=auth_headers,
        data={"rejection_reason": ""},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_reject_fragment_updates_row_and_audits(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    orders_page_integration_dsn: str,
) -> None:
    """A rejected order's row swaps in with the reason and writes audit."""
    client, _ = orders_page_admin_client
    response = await client.post(
        f"/admin/orders/fragments/{MARKET_ORDER_ID}/reject",
        headers=auth_headers,
        data={"rejection_reason": "risk limit breach"},
    )
    assert response.status_code == 200
    body = response.text
    assert f'id="order-row-{MARKET_ORDER_ID}"' in body
    assert 'data-order-status="rejected"' in body
    assert "risk limit breach" in body
    assert ">Rejected<" in body

    import asyncpg  # noqa: PLC0415

    conn = await asyncpg.connect(dsn=orders_page_integration_dsn)
    try:
        row = await conn.fetchrow(
            """
            SELECT actor, action, payload
              FROM theeyebeta.audit_log
             WHERE entity_id = $1 AND action = 'reject.order'
             ORDER BY id DESC LIMIT 1
            """,
            MARKET_ORDER_ID,
        )
    finally:
        await conn.close()
    assert row is not None
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload == {"rejection_reason": "risk limit breach"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_approve_fragment_404_for_unknown_id(
    orders_page_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """POST against a non-existent order returns 404, not 500."""
    client, _ = orders_page_admin_client
    response = await client.post(
        "/admin/orders/fragments/00000000-0000-0000-0000-000000000000/approve",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orders_page_requires_auth(
    orders_page_integration_dsn: str,
) -> None:
    """Every orders route is JWT-gated."""
    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(
        database_url=orders_page_integration_dsn,
        audit_service_url="http://127.0.0.1:7110",
    )
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/orders")
            rationale = await anon.get(
                f"/admin/orders/fragments/{LONG_ORDER_ID}/rationale",
            )
            modal = await anon.get(
                f"/admin/orders/fragments/{LONG_ORDER_ID}/reject-modal",
            )
            approve = await anon.post(
                f"/admin/orders/fragments/{LONG_ORDER_ID}/approve",
            )
            reject = await anon.post(
                f"/admin/orders/fragments/{LONG_ORDER_ID}/reject",
                data={"rejection_reason": "x"},
            )
    for resp in (page, rationale, modal, approve, reject):
        assert resp.status_code == 401


def _slice_row(body: str, order_id: str) -> str:
    """Return only the ``<tr id="order-row-{id}"…</tr>`` block."""
    marker = f'id="order-row-{order_id}"'
    idx = body.find(marker)
    assert idx != -1, f"row {order_id!r} not found"
    end = body.find("</tr>", idx)
    assert end != -1, f"row {order_id!r} unterminated"
    return body[idx : end + len("</tr>")]
