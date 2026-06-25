"""Tests for the risk/compliance pre-submission gate on the approve endpoint."""

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

_ROW = {
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


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test:test@localhost/db",
        nats_url="nats://127.0.0.1:4222",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_rejects_on_risk_block() -> None:
    """A risk-service block stops the order before it ever reaches manager.approve()."""
    app = create_app(_settings())

    with (
        patch("oms.app.fetch_order_row", AsyncMock(return_value=_ROW)),
        patch(
            "oms.app.check_risk",
            AsyncMock(return_value={"approved": False, "reason": "position_size_pct breach"}),
        ),
        patch("oms.app.check_compliance", AsyncMock()) as mock_compliance,
        patch("oms.app.persist_order_rejection", AsyncMock()) as mock_reject,
        patch("oms.app.insert_audit_log", AsyncMock()) as mock_audit,
        patch("oms.state.OrderManager.approve", AsyncMock()) as mock_approve,
        patch("oms.reconciliation.ReconciliationLoop.start", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.start", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.stop", AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/oms/orders/{ORDER_ID}/approve")

    assert response.status_code == 422
    assert "position_size_pct" in response.json()["detail"]
    mock_reject.assert_awaited_once()
    mock_audit.assert_awaited_once()
    assert mock_audit.await_args.kwargs["payload"]["source"] == "risk_service"
    mock_compliance.assert_not_called()
    mock_approve.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_rejects_on_compliance_block() -> None:
    """A compliance-service block stops the order even when risk approves."""
    app = create_app(_settings())

    with (
        patch("oms.app.fetch_order_row", AsyncMock(return_value=_ROW)),
        patch("oms.app.check_risk", AsyncMock(return_value={"approved": True})),
        patch(
            "oms.app.check_compliance",
            AsyncMock(return_value={"approved": False, "reason": "legal hold active"}),
        ),
        patch("oms.app.persist_order_rejection", AsyncMock()) as mock_reject,
        patch("oms.app.insert_audit_log", AsyncMock()) as mock_audit,
        patch("oms.state.OrderManager.approve", AsyncMock()) as mock_approve,
        patch("oms.reconciliation.ReconciliationLoop.start", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.start", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.stop", AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/oms/orders/{ORDER_ID}/approve")

    assert response.status_code == 422
    assert "legal hold" in response.json()["detail"]
    mock_reject.assert_awaited_once()
    assert mock_audit.await_args.kwargs["payload"]["source"] == "compliance_service"
    mock_approve.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_proceeds_when_both_gates_approve() -> None:
    """Submission continues normally once both risk and compliance approve."""
    app = create_app(_settings())

    with (
        patch("oms.app.fetch_order_row", AsyncMock(return_value=_ROW)),
        patch("oms.state.fetch_order_row", AsyncMock(return_value=_ROW)),
        patch("oms.state.persist_order_state", AsyncMock()),
        patch("oms.app.check_risk", AsyncMock(return_value={"approved": True})) as mock_risk,
        patch(
            "oms.app.check_compliance",
            AsyncMock(return_value={"approved": True}),
        ) as mock_compliance,
        patch("oms.app.persist_order_rejection", AsyncMock()) as mock_reject,
        patch("oms.app.insert_audit_log", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.start", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.start", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.publish_approved", AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/oms/orders/{ORDER_ID}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "submitted"
    mock_risk.assert_awaited_once()
    mock_compliance.assert_awaited_once()
    mock_reject.assert_not_called()
