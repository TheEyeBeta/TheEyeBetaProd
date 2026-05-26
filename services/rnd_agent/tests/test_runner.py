"""Unit tests for RNDRunner guard integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rnd_agent.guard_client import GuardResult  # noqa: E402
from rnd_agent.models import RndAgentOutput  # noqa: E402
from rnd_agent.runner import RNDRunner  # noqa: E402
from rnd_agent.settings import Settings  # noqa: E402

_VALID_PROPOSAL = {
    "proposals": [
        {
            "category": "strategy_param",
            "target": "momentum.lookback",
            "current_value": {"days": 20},
            "proposed_value": {"days": 30},
            "rationale": "backtest.abc.sharpe improved per snapshot.technicals.AAPL.rsi14",
            "evidence": {"notes": ["backtest.abc.sharpe"]},
            "estimated_impact": {
                "confidence": 0.7,
                "expected_direction": "improve",
                "summary": "Higher Sharpe in walk-forward",
            },
        }
    ]
}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_forbidden_target_probe_inserts_zero_proposals() -> None:
    """Guard rejection yields zero proposals; violations are surfaced."""
    settings = Settings(
        rnd_database_url="postgresql://tb_rnd_readonly:test@127.0.0.1:5432/theeyebeta",
        litellm_key_rnd_agent="sk-test",
        dry_run=False,
    )
    runner = RNDRunner(settings)
    run_id = uuid4()

    mock_guard = GuardResult(
        approved=False,
        outcome="RETRY",
        violations=[
            {
                "type": "forbidden_target",
                "severity": "high",
                "detail": "audit_log mentioned",
            },
        ],
        sanitized_output=json.dumps(_VALID_PROPOSAL),
    )
    mock_chat = MagicMock(content=json.dumps(_VALID_PROPOSAL))

    with (
        patch("rnd_agent.runner.create_agent_run", AsyncMock(return_value=run_id)),
        patch("rnd_agent.runner.gather_research_inputs", AsyncMock(return_value={})),
        patch("rnd_agent.runner.finish_agent_run", AsyncMock()),
        patch("rnd_agent.runner.insert_proposals", AsyncMock()) as mock_insert,
        patch("rnd_agent.runner.validate_rnd_output", AsyncMock(return_value=mock_guard)),
        patch("rnd_agent.runner.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.__aenter__.return_value = mock_llm
        mock_llm.__aexit__.return_value = None
        mock_llm.chat = AsyncMock(return_value=mock_chat)
        mock_llm_cls.return_value = mock_llm

        result = await runner.run(forbidden_target_probe=True)

    assert result.proposal_ids == []
    assert result.guard_outcome == "RETRY"
    assert result.violations[0]["type"] == "forbidden_target"
    mock_insert.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dry_run_inserts_zero_even_when_guard_passes() -> None:
    """Dry run validates but does not persist proposals."""
    settings = Settings(
        rnd_database_url="postgresql://tb_rnd_readonly:test@127.0.0.1:5432/theeyebeta",
        litellm_key_rnd_agent="sk-test",
        dry_run=True,
    )
    runner = RNDRunner(settings)
    run_id = uuid4()
    mock_guard = GuardResult(
        approved=True,
        outcome="PASS",
        violations=[],
        sanitized_output=json.dumps(_VALID_PROPOSAL),
    )
    mock_chat = MagicMock(content=json.dumps(_VALID_PROPOSAL))

    with (
        patch("rnd_agent.runner.create_agent_run", AsyncMock(return_value=run_id)),
        patch("rnd_agent.runner.gather_research_inputs", AsyncMock(return_value={})),
        patch("rnd_agent.runner.finish_agent_run", AsyncMock()),
        patch("rnd_agent.runner.insert_proposals", AsyncMock()) as mock_insert,
        patch("rnd_agent.runner.validate_rnd_output", AsyncMock(return_value=mock_guard)),
        patch("rnd_agent.runner.LLMClient") as mock_llm_cls,
    ):
        mock_llm = AsyncMock()
        mock_llm.__aenter__.return_value = mock_llm
        mock_llm.__aexit__.return_value = None
        mock_llm.chat = AsyncMock(return_value=mock_chat)
        mock_llm_cls.return_value = mock_llm

        result = await runner.run()

    assert result.proposal_ids == []
    assert result.dry_run is True
    mock_insert.assert_not_called()


@pytest.mark.unit
def test_proposal_schema_max_three() -> None:
    """Schema v2 allows at most three proposals."""
    from zinc_schemas.constitution import load_constitution

    constitution = load_constitution(
        Path(__file__).resolve().parents[3] / "agents" / "rnd" / "rnd_agent.agent.md",
    )
    validator = constitution.output_validator()
    four = {"proposals": [_VALID_PROPOSAL["proposals"][0]] * 4}
    errors = list(validator.iter_errors(four))
    assert errors

    parsed = RndAgentOutput.model_validate(_VALID_PROPOSAL)
    assert len(parsed.proposals) <= 3
