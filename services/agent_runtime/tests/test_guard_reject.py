"""Guard REJECT must not produce agent_decisions rows."""

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

from agent_runtime.guard_client import GuardRejectedError, GuardValidationResult
from agent_runtime.runner import AgentRunner, _TokenTotals
from agent_runtime.schemas import AgentOutput


@pytest.mark.unit
@pytest.mark.asyncio
async def test_guard_reject_skips_agent_decisions() -> None:
    """REJECT outcome finalizes run as failed without inserting decisions."""
    runner = AgentRunner(database_url="postgresql://unused/test", llm_virtual_key="sk-test")
    run_id = uuid4()
    parsed = AgentOutput.model_validate(
        {
            "market_stance": "neutral",
            "regime_call": "ranging",
            "decisions": [
                {
                    "instrument_symbol": "AAPL",
                    "decision": "HOLD",
                    "confidence": 0.5,
                    "horizon_days": 10,
                    "key_drivers": ["macro.us.dgs10"],
                    "rationale": "technicals.AAPL.rsi14 at 55.",
                },
            ],
        },
    )
    reject = GuardValidationResult(
        approved=False,
        violations=[{"type": "schema", "detail": "forced reject"}],
        outcome="REJECT",
    )

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "agent_runtime.runner.validate_agent_output",
            AsyncMock(return_value=reject),
        ),
        patch("agent_runtime.runner.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)),
        pytest.raises(GuardRejectedError),
    ):
        await runner._guard_until_pass(
            agent_id="macro-lead",
            run_id=str(run_id),
            constitution=MagicMock(output_schema_version=1),
            llm=AsyncMock(),
            math_tool=AsyncMock(),
            snapshot_id=uuid4(),
            snapshot_data={"universe": [{"symbol": "AAPL"}]},
            parsed=parsed,
            raw_text=json.dumps(parsed.model_dump()),
            tool_calls=[],
            valid_symbols={"AAPL"},
            primary_model="claude-sonnet-4-6",
            fallback_model=None,
            totals=_TokenTotals(),
        )

    with patch("agent_runtime.runner.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        await runner._finalize_guard_reject(
            run_id,
            "macro-lead",
            GuardRejectedError([{"type": "schema", "detail": "x"}]),
        )

    sql_calls = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert not any("agent_decisions" in sql for sql in sql_calls)
    assert any("agent_runs" in sql and "status" in sql for sql in sql_calls)
