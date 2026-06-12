"""Unit tests for canonical→public price mirror de-dup and DO NOTHING semantics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from scripts.mirror_canonical_prices_to_public import (
    CanonicalPriceMirrorWorker,
    MirrorRow,
    dedupe_mirror_rows,
    insert_mirror_batch,
    planned_mirror_writes,
)


def _row(ticker_id: int, *, close: str = "10.0") -> MirrorRow:
    return MirrorRow(
        ticker_id=ticker_id,
        trade_date=date(2026, 6, 9),
        open=Decimal("9.0"),
        high=Decimal("11.0"),
        low=Decimal("8.0"),
        close=Decimal(close),
        adj_close=Decimal(close),
        volume=1_000,
    )


def test_dedupe_mirror_rows_keeps_last_per_conflict_key() -> None:
    rows = [_row(1, close="10.0"), _row(1, close="11.0"), _row(2, close="20.0")]

    deduped = dedupe_mirror_rows(rows)

    assert len(deduped) == 2
    by_ticker = {row.ticker_id: row for row in deduped}
    assert by_ticker[1].close == Decimal("11.0")
    assert by_ticker[2].close == Decimal("20.0")


def test_planned_mirror_writes_excludes_existing_keys() -> None:
    rows = [_row(1), _row(2), _row(3)]
    existing = {(2, date(2026, 6, 9))}

    planned = planned_mirror_writes(rows, existing)

    assert [row.ticker_id for row in planned] == [1, 3]


def test_planned_mirror_writes_dedupes_before_filtering() -> None:
    rows = [_row(1, close="10.0"), _row(1, close="12.0")]
    existing: set[tuple[int, date]] = set()

    planned = planned_mirror_writes(rows, existing)

    assert len(planned) == 1
    assert planned[0].close == Decimal("12.0")


@pytest.mark.asyncio
async def test_insert_mirror_batch_counts_only_conflicts_skipped() -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=["INSERT 0 1", "INSERT 0 0", "INSERT 0 1"])
    batch = [_row(1), _row(2), _row(3)]

    written = await insert_mirror_batch(conn, batch)

    assert written == 2
    assert conn.execute.await_count == 3
    first_sql = conn.execute.await_args_list[0].args[0]
    assert "ON CONFLICT (ticker_id, date) DO NOTHING" in first_sql
    assert conn.execute.await_args_list[0].args[-1] == "canonical_mirror"


@pytest.mark.asyncio
async def test_dry_run_reports_zero_planned_when_public_already_present() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[date(2026, 6, 9), 499])
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {
                    "ticker_id": 101,
                    "open": Decimal("1"),
                    "high": Decimal("2"),
                    "low": Decimal("1"),
                    "close": Decimal("1.5"),
                    "adj_close": Decimal("1.5"),
                    "volume": 100,
                },
            ],
            [{"ticker_id": 101}],
        ],
    )
    worker = CanonicalPriceMirrorWorker(database_url="postgresql://unused/unused")

    result = await worker.execute(conn, date(2026, 6, 9), dry_run=True)

    assert result.metadata["planned_writes"] == 0
    assert result.metadata["canonical_bars"] == 1
    assert result.records_expected == 499
    conn.execute.assert_not_called()
