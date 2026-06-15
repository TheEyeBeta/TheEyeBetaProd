"""Unit tests for the daily pipeline runner."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

from workers.base_worker import WorkerResult
from workers.daily_pipeline_runner import DailyPipelineRunner


def _runner() -> DailyPipelineRunner:
    return DailyPipelineRunner(database_url="postgresql://unused/unused")


async def test_dry_run_reports_indicator_compute() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=True)

    result = await _runner().execute(conn, date(2026, 6, 12), dry_run=True)

    assert result.metadata["would_run"] == "workers.indicator_compute_worker"


async def test_execute_delegates_to_indicator_compute() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=True)
    compute_result = WorkerResult(
        records_written=100,
        records_expected=120,
        metadata={"computed": 100},
    )
    with patch(
        "workers.daily_pipeline_runner.IndicatorComputeWorker.execute",
        AsyncMock(return_value=compute_result),
    ) as compute:
        result = await _runner().execute(conn, date(2026, 6, 10), dry_run=False)

    compute.assert_awaited_once()
    assert result.records_written == 100
    assert result.metadata["engine"] == "indicator_compute"


async def test_non_trading_day_skips() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=False)

    result = await _runner().execute(conn, date(2026, 6, 13), dry_run=False)

    assert result.metadata == {"skipped": True, "reason": "non_trading_day"}
