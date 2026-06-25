"""A hung LLM-loop call must fail the run instead of leaving it RUNNING forever."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent_runtime.runner import AgentRunner  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hung_llm_loop_marks_run_failed_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `_llm_loop` call that never returns must be cut off by the timeout."""
    monkeypatch.setattr("agent_runtime.runner._AGENT_RUN_TIMEOUT_SECONDS", 0.05)

    runner = AgentRunner(database_url="postgresql://unused/test", llm_virtual_key="sk-test")
    run_id = uuid4()

    agents_cursor = AsyncMock()
    agents_cursor.fetchone = AsyncMock(return_value=("constitution.yaml", "model-a", "model-b"))
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=agents_cursor)
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    loader = AsyncMock()
    loader.load = AsyncMock(
        return_value={"market": "US", "universe": [{"symbol": "AAPL", "instrument_id": 1}]},
    )

    llm_cm = AsyncMock()
    llm_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    llm_cm.__aexit__ = AsyncMock(return_value=None)

    async def _never_returns(**_kwargs: object) -> None:
        await asyncio.sleep(10)

    with (
        patch("agent_runtime.runner.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)),
        patch("agent_runtime.runner.load_constitution", MagicMock(return_value=MagicMock())),
        patch("agent_runtime.runner.LLMClient", MagicMock(return_value=llm_cm)),
        patch.object(AgentRunner, "_llm_loop", AsyncMock(side_effect=_never_returns)),
        pytest.raises(TimeoutError),
    ):
        await runner._run_inner("macro-lead", uuid4(), run_id, loader)

    sql_calls = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
    assert any("status = 'failed'" in sql for sql in sql_calls)
