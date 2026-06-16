"""Unit tests for submission gate pause sources."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from oms.submission_gate import PauseSource, SubmissionGate  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_is_paused_when_either_source_active() -> None:
    """Any active pause source blocks submissions."""
    gate = SubmissionGate(redis_url=None)

    assert not await gate.is_paused()

    await gate.pause(source=PauseSource.RECONCILIATION, reason="drift")
    assert await gate.is_paused()
    assert await gate.is_source_paused(PauseSource.RECONCILIATION)
    assert not await gate.is_source_paused(PauseSource.EMERGENCY)

    await gate.resume(source=PauseSource.RECONCILIATION)
    assert not await gate.is_paused()

    await gate.pause(source=PauseSource.EMERGENCY, reason="halt")
    assert await gate.is_paused()
    assert await gate.is_source_paused(PauseSource.EMERGENCY)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resume_only_clears_target_source() -> None:
    """Resuming one source leaves other pause sources active."""
    gate = SubmissionGate(redis_url=None)
    await gate.pause(source=PauseSource.RECONCILIATION, reason="drift")
    await gate.pause(source=PauseSource.EMERGENCY, reason="halt")

    await gate.resume(source=PauseSource.RECONCILIATION)

    assert await gate.is_paused()
    assert not await gate.is_source_paused(PauseSource.RECONCILIATION)
    assert await gate.is_source_paused(PauseSource.EMERGENCY)
