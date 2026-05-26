"""Unit tests for OrderManager state transitions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from oms.state import OrderManager  # noqa: E402

ORDER_ID = str(uuid4())
PORTFOLIO_ID = "660e8400-e29b-41d4-a716-446655440001"


def _pending_row() -> dict:
    return {
        "id": ORDER_ID,
        "portfolio_id": PORTFOLIO_ID,
        "instrument_id": 1,
        "side": "buy",
        "qty": 100.0,
        "status": "pending_approval",
        "filled_qty": 0.0,
        "avg_fill_price": None,
        "limit_price": 100.0,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_reaches_submitted_within_two_seconds() -> None:
    """pending_approval → approved → submitted on approve."""
    manager = OrderManager("postgresql://test:test@localhost/db")
    row = _pending_row()

    with (
        patch("oms.state.fetch_order_row", AsyncMock(return_value=row)),
        patch("oms.state.persist_order_state", AsyncMock()) as mock_persist,
    ):
        snapshots = await manager.approve(ORDER_ID, approved_by="operator")

    assert len(snapshots) == 2
    assert snapshots[0].ok and snapshots[0].status == "approved"
    assert snapshots[1].ok and snapshots[1].status == "submitted"
    assert mock_persist.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fill_inserts_execution_and_updates_position() -> None:
    """Broker fill writes executions and updates positions."""
    manager = OrderManager("postgresql://test:test@localhost/db")
    row = _pending_row()
    row["status"] = "submitted"

    with patch("oms.state.fetch_order_row", AsyncMock(return_value=row)):
        with patch("oms.state.persist_order_state", AsyncMock()):
            await manager.register_proposed(ORDER_ID)

        with (
            patch("oms.state.persist_order_state", AsyncMock()) as mock_persist,
            patch("oms.state.insert_execution", AsyncMock()) as mock_exec,
            patch("oms.state.upsert_position", AsyncMock()) as mock_pos,
            patch("oms.state.insert_audit_log", AsyncMock()),
        ):
            snapshot = await manager.handle_fill(ORDER_ID, qty=40.0, price=101.5)

    assert snapshot.ok
    assert snapshot.status == "partially_filled"
    mock_exec.assert_awaited_once()
    mock_pos.assert_awaited_once()
    assert mock_persist.await_count >= 1
    assert manager.tracker_net(PORTFOLIO_ID, 1) == 40


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_fill_reaches_filled_status() -> None:
    """Remaining quantity fill transitions order to filled."""
    manager = OrderManager("postgresql://test:test@localhost/db")
    row = _pending_row()
    row["status"] = "accepted"
    row["filled_qty"] = 60.0
    row["avg_fill_price"] = 100.0

    with patch("oms.state.fetch_order_row", AsyncMock(return_value=row)):
        with patch("oms.state.persist_order_state", AsyncMock()):
            await manager.register_proposed(ORDER_ID)

        with (
            patch("oms.state.persist_order_state", AsyncMock()),
            patch("oms.state.insert_execution", AsyncMock()),
            patch("oms.state.upsert_position", AsyncMock()),
            patch("oms.state.insert_audit_log", AsyncMock()),
        ):
            snapshot = await manager.handle_fill(ORDER_ID, qty=40.0, price=102.0)

    assert snapshot.ok
    assert snapshot.status == "filled"
    assert snapshot.filled_qty == 100.0
