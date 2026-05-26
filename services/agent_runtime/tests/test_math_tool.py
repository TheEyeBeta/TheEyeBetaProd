"""Unit tests for MathTool.compute_stat."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from agent_runtime.math_tool import ComputeStatRequest, MathTool


@pytest.mark.unit
@patch("agent_runtime.math_tool._dispatch", return_value=[50.0, 55.0, 60.0])
async def test_compute_stat_dispatches(_mock_dispatch) -> None:
    """compute_stat delegates to the zinc_native dispatcher."""
    tool = MathTool(llm_client=None)
    req = ComputeStatRequest(
        kernel="ta",
        operation="rsi",
        params={"closes": [1.0, 2.0, 3.0], "period": 3},
    )
    resp = await tool.compute_stat(req)
    assert resp.kernel == "ta"
    assert resp.operation == "rsi"
    _mock_dispatch.assert_called_once()


@pytest.mark.unit
@patch("agent_runtime.math_tool._dispatch", return_value=-1.0)
async def test_compute_stat_logs_tool_run(_mock_dispatch) -> None:
    """Tool calls persist model_runs rows when an LLM client is wired."""
    mock_llm = AsyncMock()
    mock_llm.record_tool_run = AsyncMock()
    tool = MathTool(llm_client=mock_llm)
    req = ComputeStatRequest(
        kernel="risk",
        operation="historical_var",
        params={"samples": [-1.0, 0.0, 1.0, 2.0], "alpha": 0.25},
    )
    await tool.compute_stat(req)
    mock_llm.record_tool_run.assert_awaited_once()
    assert "compute_stat" in mock_llm.record_tool_run.await_args.kwargs["tool_name"]
