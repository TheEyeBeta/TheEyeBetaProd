"""Replay guard PASS outputs produce agent_decisions matching fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent_runtime.guard_client import GuardValidationResult
from agent_runtime.runner import AgentRunner, _TokenTotals
from agent_runtime.schemas import AgentOutput

_FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "guard_service"
    / "tests"
    / "fixtures"
    / "replay_outputs.json"
)


@pytest.fixture
def replay_cases() -> list[dict]:
    """Shared replay fixtures from guard_service."""
    return json.loads(_FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_guard_pass_yields_matching_decision_rows(replay_cases: list[dict]) -> None:
    """When guard returns PASS, persisted decision fields match historical replay."""
    runner = AgentRunner(database_url="postgresql://unused/test", llm_virtual_key="sk-test")

    for case in replay_cases:
        parsed = AgentOutput.model_validate(json.loads(case["raw_output"]))
        pass_result = GuardValidationResult(
            approved=True,
            violations=[],
            outcome="PASS",
            sanitized_output=case["raw_output"],
        )

        with patch(
            "agent_runtime.runner.validate_agent_output",
            AsyncMock(return_value=pass_result),
        ):
            guarded = await runner._guard_until_pass(
                agent_id=case["agent_id"],
                run_id=str(uuid4()),
                constitution=AsyncMock(),  # unused when validate mocked
                llm=AsyncMock(),
                math_tool=AsyncMock(),
                snapshot_id=uuid4(),
                snapshot_data=case["snapshot"],
                parsed=parsed,
                raw_text=case["raw_output"],
                tool_calls=[],
                valid_symbols=set(case["valid_symbols"]),
                primary_model="claude-sonnet-4-6",
                fallback_model=None,
                totals=_TokenTotals(),
            )

        assert guarded.market_stance == parsed.market_stance
        for decision, expected in zip(guarded.decisions, case["expected_decisions"], strict=True):
            assert decision.instrument_symbol == expected["instrument_symbol"]
            assert decision.decision == expected["decision"]
            assert decision.confidence == pytest.approx(expected["confidence"])
            assert decision.horizon_days == expected["horizon_days"]
