"""Unit tests for LatestSnapshotWorker."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

from workers.latest_snapshot_worker import (
    MATERIALIZE_SQL,
    LatestSnapshotWorker,
    materialize_latest_snapshots,
)


def _worker() -> LatestSnapshotWorker:
    return LatestSnapshotWorker(database_url="postgresql://unused/unused")


async def test_dry_run_reports_priced_instruments() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            511,  # active universe
            501,  # rows_before
            480,  # priced instruments
        ],
    )

    result = await _worker().execute(conn, date(2026, 6, 16), dry_run=True)

    assert result.metadata["dry_run"] is True
    assert result.metadata["active_universe"] == 511
    assert result.metadata["priced_instruments"] == 480
    assert result.records_written == 0
    conn.execute.assert_not_called()


async def test_execute_runs_materialize_sql() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            511,  # active universe
            501,  # rows_before
            511,  # rows_after
            None,  # max_updated
        ],
    )
    conn.execute = AsyncMock(return_value="INSERT 0 511")

    with patch(
        "workers.latest_snapshot_worker.materialize_latest_snapshots",
        AsyncMock(return_value=511),
    ) as materialize:
        result = await _worker().execute(conn, date(2026, 6, 16), dry_run=False)

    materialize.assert_awaited_once_with(conn)
    assert result.records_written == 511
    assert result.metadata["written"] == 511


async def test_materialize_latest_snapshots_parses_insert_count() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 42")

    written = await materialize_latest_snapshots(conn)

    assert written == 42
    conn.execute.assert_awaited_once_with(MATERIALIZE_SQL)


async def test_partial_data_still_upserts_when_price_exists() -> None:
    """Instruments with prices but no indicators should still be materialized."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            1,  # active universe
            0,  # rows_before
            1,  # rows_after
            None,  # max_updated
        ],
    )

    with patch(
        "workers.latest_snapshot_worker.materialize_latest_snapshots",
        AsyncMock(return_value=1),
    ):
        result = await _worker().execute(conn, date(2026, 6, 16), dry_run=False)

    assert result.records_written == 1
