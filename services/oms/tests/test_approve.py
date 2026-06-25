"""Tests for approve HTTP endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from oms.app import create_app  # noqa: E402
from oms.settings import Settings  # noqa: E402

ORDER_ID = uuid4()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_endpoint_returns_submitted() -> None:
    """POST /oms/orders/{id}/approve returns submitted status."""
    settings = Settings(
        database_url="postgresql://test:test@localhost/db",
        nats_url="nats://127.0.0.1:4222",
    )
    app = create_app(settings)

    row = {
        "id": str(ORDER_ID),
        "portfolio_id": "660e8400-e29b-41d4-a716-446655440001",
        "instrument_id": 1,
        "side": "buy",
        "qty": 50.0,
        "status": "pending_approval",
        "filled_qty": 0.0,
        "avg_fill_price": None,
        "limit_price": 100.0,
    }

    with (
        patch("oms.app.fetch_order_row", AsyncMock(return_value=row)),
        patch("oms.state.fetch_order_row", AsyncMock(return_value=row)),
        patch("oms.state.persist_order_state", AsyncMock()),
        patch("oms.app.insert_audit_log", AsyncMock()),
        patch("oms.app.check_risk", AsyncMock(return_value={"approved": True})),
        patch("oms.app.check_compliance", AsyncMock(return_value={"approved": True})),
        patch("oms.reconciliation.ReconciliationLoop.start", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.start", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.publish_approved", AsyncMock()) as mock_pub,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/oms/orders/{ORDER_ID}/approve",
                json={"approved_by": "ops"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["transitions"][-1]["status"] == "submitted"
    mock_pub.assert_awaited_once()
