"""Unit tests for IndicatorComputeWorker."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from workers.indicator_compute_worker import IndicatorComputeWorker, load_price_history


def _worker() -> IndicatorComputeWorker:
    return IndicatorComputeWorker(database_url="postgresql://unused/unused")


async def test_dry_run_counts_planned_rows() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            True,  # is_trading_day
            2,  # priced_today
            0,  # rows_before
        ],
    )
    conn.fetch = AsyncMock(
        return_value=[
            {"instrument_id": 1, "ticker_id": 10},
            {"instrument_id": 2, "ticker_id": 20},
        ],
    )
    target = date(2026, 6, 12)
    history = [(target, 100.0, 101.0, 99.0, 1_000_000)]
    fake_row = object()

    with (
        patch(
            "workers.indicator_compute_worker.load_price_history",
            AsyncMock(return_value=history),
        ),
        patch(
            "workers.indicator_compute_worker.compute_indicators",
            return_value=fake_row,
        ),
        patch(
            "workers.indicator_compute_worker.indicator_row_to_bind",
            return_value=(1, target, 10),
        ),
    ):
        result = await _worker().execute(conn, target, dry_run=True)

    assert result.metadata["dry_run"] is True
    assert result.metadata["planned"] == 2
    assert result.metadata["priced_today"] == 2


async def test_non_trading_day_skips() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=False)

    result = await _worker().execute(conn, date(2026, 6, 14), dry_run=False)

    assert result.metadata == {"skipped": True, "reason": "non_trading_day"}


async def test_load_price_history_orders_by_ts() -> None:
    conn = AsyncMock()
    start = date(2026, 1, 1)
    end = date(2026, 6, 12)
    conn.fetch = AsyncMock(
        return_value=[
            {"d": start, "close": 10.0, "high": 11.0, "low": 9.0, "volume": 100},
            {"d": end, "close": 20.0, "high": 21.0, "low": 19.0, "volume": 200},
        ],
    )

    rows = await load_price_history(conn, 42, target_date=end)

    assert len(rows) == 2
    assert rows[-1][0] == end
    fetch_args = conn.fetch.await_args.args
    assert fetch_args[1] == 42
    assert fetch_args[2] == end - timedelta(days=550)
