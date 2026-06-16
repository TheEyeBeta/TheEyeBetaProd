"""Unit tests for OMS NATS emergency-halt consumer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from oms.consumer import EMERGENCY_HALT_SUBJECT, OmsEventConsumer  # noqa: E402
from oms.state import OrderManager  # noqa: E402
from oms.submission_gate import PauseSource, SubmissionGate  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emergency_halt_subscriber_pauses_gate() -> None:
    """NATS trading.emergency.halt sets the emergency pause source."""
    gate = SubmissionGate(redis_url=None)
    manager = OrderManager("postgresql://test:test@localhost/db")
    consumer = OmsEventConsumer("nats://127.0.0.1:4222", manager, gate)

    payload = {
        "reason": "operator halt",
        "halted_by": "admin",
        "halted_at": "2026-06-16T12:00:00+00:00",
    }
    msg = MagicMock()
    msg.data = json.dumps(payload).encode()

    await consumer._handle_emergency_halt(msg)

    assert await gate.is_paused()
    assert await gate.is_source_paused(PauseSource.EMERGENCY)
    assert not await gate.is_source_paused(PauseSource.RECONCILIATION)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emergency_halt_subject_is_wired_on_start() -> None:
    """Consumer subscribes to trading.emergency.halt on start."""
    gate = SubmissionGate(redis_url=None)
    manager = OrderManager("postgresql://test:test@localhost/db")
    consumer = OmsEventConsumer("nats://127.0.0.1:4222", manager, gate)

    mock_nc = MagicMock()
    mock_nc.subscribe = AsyncMock()
    mock_nc.drain = AsyncMock()
    mock_nc.close = AsyncMock()

    with patch("oms.consumer.nats.connect", AsyncMock(return_value=mock_nc)):
        await consumer.start()

    subjects = [call.args[0] for call in mock_nc.subscribe.await_args_list]
    assert EMERGENCY_HALT_SUBJECT in subjects
    await consumer.stop()
