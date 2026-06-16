"""Unit tests for broker reconciliation loop."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from oms.reconciliation import BREACH_SUBJECT, ReconciliationLoop  # noqa: E402
from oms.submission_gate import PauseSource, SubmissionGate  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconciliation_pauses_on_intentional_position_drift() -> None:
    """Drift vs broker pauses submissions and publishes a breach event."""
    gate = SubmissionGate(redis_url=None)
    loop = ReconciliationLoop(
        "postgresql://test:test@localhost/db",
        "http://broker:7090",
        "nats://127.0.0.1:4222",
        gate,
        interval_seconds=180,
    )
    mock_nc = MagicMock()
    mock_nc.publish = AsyncMock()
    loop._nc = mock_nc

    with (
        patch.object(
            loop._broker,
            "list_positions",
            AsyncMock(return_value=[{"symbol": "AAPL", "qty": 10.0}]),
        ),
        patch.object(loop._broker, "list_orders", AsyncMock(return_value=[])),
        patch.object(
            loop,
            "_load_local_positions",
            AsyncMock(return_value=[{"symbol": "AAPL", "qty": 5.0}]),
        ),
        patch.object(loop, "_load_local_orders", AsyncMock(return_value=[])),
    ):
        result = await loop.run_once()

    assert result["ok"] is False
    assert len(result["drifts"]) == 1
    assert await gate.is_paused()
    mock_nc.publish.assert_awaited_once()
    call_args = mock_nc.publish.await_args
    assert call_args is not None
    assert call_args[0][0] == BREACH_SUBJECT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconciliation_resumes_when_drift_cleared() -> None:
    """Matching broker state clears an existing reconciliation pause."""
    gate = SubmissionGate(redis_url=None)
    await gate.pause(source=PauseSource.RECONCILIATION, reason="prior drift")
    loop = ReconciliationLoop(
        "postgresql://test:test@localhost/db",
        "http://broker:7090",
        "nats://127.0.0.1:4222",
        gate,
    )
    loop._nc = MagicMock()

    with (
        patch.object(loop._broker, "list_positions", AsyncMock(return_value=[])),
        patch.object(loop._broker, "list_orders", AsyncMock(return_value=[])),
        patch.object(loop, "_load_local_positions", AsyncMock(return_value=[])),
        patch.object(loop, "_load_local_orders", AsyncMock(return_value=[])),
    ):
        result = await loop.run_once()

    assert result["ok"] is True
    assert not await gate.is_paused()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reconciliation_does_not_clear_emergency_pause() -> None:
    """A clean reconciliation cycle must not resume an emergency halt."""
    gate = SubmissionGate(redis_url=None)
    await gate.pause(source=PauseSource.EMERGENCY, reason="admin halt")
    loop = ReconciliationLoop(
        "postgresql://test:test@localhost/db",
        "http://broker:7090",
        "nats://127.0.0.1:4222",
        gate,
    )
    loop._nc = MagicMock()

    with (
        patch.object(loop._broker, "list_positions", AsyncMock(return_value=[])),
        patch.object(loop._broker, "list_orders", AsyncMock(return_value=[])),
        patch.object(loop, "_load_local_positions", AsyncMock(return_value=[])),
        patch.object(loop, "_load_local_orders", AsyncMock(return_value=[])),
    ):
        result = await loop.run_once()

    assert result["ok"] is True
    assert await gate.is_paused()
    assert await gate.is_source_paused(PauseSource.EMERGENCY)
    assert not await gate.is_source_paused(PauseSource.RECONCILIATION)
