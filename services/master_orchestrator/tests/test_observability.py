"""Unit tests for Prometheus metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from master_orchestrator.observability import (  # noqa: E402
    debate_rounds_total,
    record_debate_round,
    record_trio_outcome,
    trios_total,
)


@pytest.mark.unit
def test_record_trio_outcome_increments_counter() -> None:
    """trios_total receives consensus/debate/skipped labels."""
    before = trios_total.labels(market="US", outcome="consensus")._value.get()  # noqa: SLF001
    record_trio_outcome("US", "consensus")
    after = trios_total.labels(market="US", outcome="consensus")._value.get()  # noqa: SLF001
    assert after >= before + 1


@pytest.mark.unit
def test_record_debate_round_increments_counter() -> None:
    """debate_rounds_total receives market and round labels."""
    before = debate_rounds_total.labels(market="US", round="1")._value.get()  # noqa: SLF001
    record_debate_round("US", 1)
    after = debate_rounds_total.labels(market="US", round="1")._value.get()  # noqa: SLF001
    assert after >= before + 1
