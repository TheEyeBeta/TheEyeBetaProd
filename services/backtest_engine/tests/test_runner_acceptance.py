"""P-BT-01 acceptance: example_swing_us 1-year run under 60s with 8 metrics."""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backtest_engine.decisions import DecisionBook  # noqa: E402
from backtest_engine.runner import BacktestRunner, RunConfig  # noqa: E402
from backtest_engine.settings import Settings  # noqa: E402

RUN_ID = uuid4()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_example_swing_us_one_year_completes_under_sixty_seconds() -> None:
    """POST /backtest/run equivalent completes with eight metric rows."""
    settings = Settings(
        database_url="postgresql://test:test@localhost/db",
        git_sha="test-sha",
        minio_secret_key="minioadmin123",  # noqa: S106
    )
    runner = BacktestRunner(settings)

    strategy_ctx = type(
        "Ctx",
        (),
        {
            "strategy_id": "example_swing_us",
            "market": "US.NASDAQ",
            "max_positions": 10,
            "agent_id": "technical-analyst",
            "mode": "replay",
        },
    )()

    with (
        patch("backtest_engine.runner.load_strategy", AsyncMock(return_value=strategy_ctx)),
        patch(
            "backtest_engine.runner.union_universe",
            AsyncMock(return_value=["SPY", "AAPL", "MSFT"]),
        ),
        patch("backtest_engine.runner.insert_backtest_run", AsyncMock(return_value=RUN_ID)),
        patch("backtest_engine.runner.update_run_universe", AsyncMock()),
        patch("backtest_engine.runner.build_parquet", AsyncMock()),
        patch(
            "backtest_engine.runner.load_replay_decisions",
            AsyncMock(return_value=DecisionBook()),
        ),
        patch("backtest_engine.runner.insert_metrics", AsyncMock()) as mock_metrics,
        patch("backtest_engine.runner.update_run_status", AsyncMock()),
        patch("backtest_engine.runner.write_pnl_parquet"),
        patch(
            "backtest_engine.runner.upload_file",
            return_value=f"s3://theeyebeta-backtests/{RUN_ID}/pnl.parquet",
        ),
    ):
        started = time.perf_counter()
        result = await runner.run(
            RunConfig(
                strategy_id="example_swing_us",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                walk_forward=False,
                mode="replay",
            ),
        )
        elapsed = time.perf_counter() - started

    assert elapsed < 60.0
    assert result.status == "succeeded"
    assert len(result.metrics) == 8
    mock_metrics.assert_awaited_once()
    metric_names = {row[0] for row in mock_metrics.await_args.args[2]}
    assert metric_names == {
        "sharpe",
        "sortino",
        "calmar",
        "max_dd",
        "hit_rate",
        "avg_win",
        "avg_loss",
        "turnover",
    }
