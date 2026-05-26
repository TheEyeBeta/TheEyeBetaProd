"""Unit tests for disagreement detection and debate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from master_orchestrator.debate import DebateRound
from master_orchestrator.disagreement import decisions_disagree
from master_orchestrator.models import AgentDecisionView, AgentRunResult

SNAPSHOT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


def _agent_result(
    agent_id: str,
    *,
    decision: str = "HOLD",
    confidence: float = 0.65,
) -> AgentRunResult:
    run_id = str(uuid4())
    return AgentRunResult(
        agent_id=agent_id,
        run_id=run_id,
        snapshot_id=str(SNAPSHOT_ID),
        market_stance="neutral",
        regime_call="ranging",
        decisions=[
            AgentDecisionView(
                agent_id=agent_id,
                run_id=run_id,
                instrument_symbol="AAPL",
                instrument_id=1,
                decision=decision,  # type: ignore[arg-type]
                confidence=confidence,
                horizon_days=10,
                rationale="technicals.AAPL.rsi14 at 55.",
            ),
        ],
    )


@pytest.mark.unit
def test_decisions_disagree_buy_vs_sell(disagreeing_trio: list) -> None:
    """BUY vs SELL spans more than one step."""
    assert decisions_disagree(disagreeing_trio) is True


@pytest.mark.unit
def test_decisions_agree_on_hold(aligned_trio: list) -> None:
    """Aligned HOLD outputs skip debate."""
    assert decisions_disagree(aligned_trio) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_bounded_two_rounds(disagreeing_trio: list) -> None:
    """Debate runs at most two rebuttal rounds."""
    client = AsyncMock()
    rebuttal_hold = _agent_result("macro-lead", decision="HOLD")
    client.run_agent = AsyncMock(return_value=rebuttal_hold)

    debate = DebateRound(client)
    transcript = await debate.run(disagreeing_trio, SNAPSHOT_ID)

    assert len(transcript.rounds) <= 6  # 3 agents * up to 2 rounds
    assert transcript.final_results
    assert client.run_agent.await_count >= 3
