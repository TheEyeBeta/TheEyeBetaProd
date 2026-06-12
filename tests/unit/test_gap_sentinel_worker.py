"""Unit tests for gap sentinel canonical freshness checks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from workers.gap_sentinel_worker import (
    check_canonical_freshness,
    check_pipeline_calendar_gaps,
    check_stuck_worker_runs,
    expected_latest_trading_day,
    freshness_as_of,
)


def test_freshness_as_of_uses_wall_clock_for_current_date() -> None:
    now = datetime(2026, 6, 10, 7, 30, tzinfo=UTC)

    result = freshness_as_of(date(2026, 6, 10), now=now)

    assert result == now


def test_freshness_as_of_uses_end_of_day_for_past_date() -> None:
    now = datetime(2026, 6, 10, 7, 30, tzinfo=UTC)

    result = freshness_as_of(date(2026, 6, 8), now=now)

    assert result.date() == date(2026, 6, 8)
    assert result.hour == 23
    assert result.minute == 59


@pytest.mark.asyncio
async def test_expected_latest_trading_day_excludes_today_before_close() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=date(2026, 6, 9))

    result = await expected_latest_trading_day(
        conn,
        as_of=datetime(2026, 6, 10, 15, 0, tzinfo=UTC),
    )

    assert result == date(2026, 6, 9)
    conn.fetchval.assert_awaited_once()
    assert conn.fetchval.await_args.args[1] == date(2026, 6, 10)


@pytest.mark.asyncio
async def test_check_canonical_freshness_flags_stale_day_dry_run() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            date(2026, 6, 9),  # expected_latest_trading_day
            513,  # active universe
            date(2026, 6, 1),  # latest theeyebeta day
            499,  # latest day count
        ],
    )

    result = await check_canonical_freshness(
        conn,
        as_of=datetime(2026, 6, 10, 15, 0, tzinfo=UTC),
        dry_run=True,
    )

    assert result["violation"] is True
    assert result["expected_trading_day"] == "2026-06-09"
    assert result["latest_theeyebeta_day"] == "2026-06-01"
    assert result["gaps_created"] == []
    assert result["alerts_created"] == []


@pytest.mark.asyncio
async def test_check_canonical_freshness_creates_gap_when_stale() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            date(2026, 6, 9),
            513,
            date(2026, 6, 1),
            499,
            None,  # no existing gap
            9001,  # new gap_id
            8001,  # new alert_id
        ],
    )

    result = await check_canonical_freshness(
        conn,
        as_of=datetime(2026, 6, 10, 15, 0, tzinfo=UTC),
        dry_run=False,
    )

    assert result["violation"] is True
    assert result["gaps_created"] == [9001]
    assert result["alerts_created"] == [8001]
    assert conn.fetchval.await_count == 7


@pytest.mark.asyncio
async def test_pipeline_calendar_gaps_dry_run_writes_nothing() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        side_effect=[
            [{"calendar_date": date(2026, 6, 9)}],  # trading days
            [],  # stuck runs
        ],
    )
    conn.fetchval = AsyncMock(return_value=None)  # no COMPLETED row → day is missing

    result = await check_pipeline_calendar_gaps(conn, as_of=date(2026, 6, 10), dry_run=True)

    assert result["missing_pipeline_days"] == ["2026-06-09"]
    assert result["gaps_created"] == []
    assert result["alerts_created"] == []
    # Only the COMPLETED-row probe may run; no INSERTs.
    assert conn.fetchval.await_count == 1


@pytest.mark.asyncio
async def test_stuck_worker_runs_dry_run_reports_without_alerts() -> None:
    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "run_id": 42,
                "worker_name": "BackfillPrices",
                "trade_date": date(2026, 6, 10),
                "started_at": datetime(2026, 6, 10, 4, 0, tzinfo=UTC),
            },
        ],
    )
    conn.fetchval = AsyncMock()

    result = await check_stuck_worker_runs(conn, dry_run=True)

    assert result == [{"alert_id": None, "worker_name": "BackfillPrices", "run_id": 42}]
    conn.fetchval.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_canonical_freshness_passes_when_current() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            date(2026, 6, 9),
            513,
            date(2026, 6, 9),
            500,
        ],
    )

    result = await check_canonical_freshness(
        conn,
        as_of=datetime(2026, 6, 10, 15, 0, tzinfo=UTC),
        dry_run=False,
    )

    assert result["violation"] is False
    assert result["gaps_created"] == []
    assert result["alerts_created"] == []
