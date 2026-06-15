"""Unit tests for sector aggregation math and policies."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from workers.sector_aggregation_worker import (
    InstrumentInputs,
    SectorAggregationWorker,
    aggregate_sectors,
    compute_window_return,
    instrument_inputs_from_row,
)


def _inst(
    symbol: str,
    sector: str,
    *,
    r1: float | None = None,
    r5: float | None = None,
    r30: float | None = None,
    rsi: float | None = None,
    above50: bool | None = None,
    above200: bool | None = None,
    vr: float | None = None,
) -> InstrumentInputs:
    return InstrumentInputs(
        symbol=symbol,
        sector=sector,
        return_1d=r1,
        return_5d=r5,
        return_30d=r30,
        rsi_14=rsi,
        above_sma_50=above50,
        above_sma_200=above200,
        volume_ratio_20d=vr,
    )


def test_window_return_math_synthetic_series() -> None:
    # Newest-first closes: 110 today, 100 one trading row back, 88 thirty back.
    closes = [110.0, 100.0, *[95.0] * 28, 88.0, 80.0]
    assert compute_window_return(closes, 1) == pytest.approx(0.10)
    assert compute_window_return(closes, 30) == pytest.approx(110.0 / 88.0 - 1.0)
    # Insufficient history -> None (need window+1 rows).
    assert compute_window_return(closes[:30], 30) is None


def test_instrument_inputs_from_row_returns_and_breadth() -> None:
    row = {
        "symbol": "AAA",
        "sector": "Tech",
        "close_d": 110.0,
        "volume_d": 3000.0,
        "close_1": 100.0,
        "close_5": 88.0,
        "close_30": 55.0,
        "avg_volume_20d": 1500.0,
        "rsi_14": 61.5,
        "sma_50": 105.0,
        "sma_200": 120.0,
    }
    inst = instrument_inputs_from_row(row)
    assert inst.return_1d == pytest.approx(0.10)
    assert inst.return_5d == pytest.approx(0.25)
    assert inst.return_30d == pytest.approx(1.0)
    assert inst.above_sma_50 is True
    assert inst.above_sma_200 is False
    assert inst.volume_ratio_20d == pytest.approx(2.0)


def test_null_policy_excludes_then_nulls() -> None:
    # 3 members, 1 missing rsi (33% > 30%) -> sector median_rsi NULL.
    # returns missing for 0 members -> mean computed.
    members = [
        _inst("A", "Tech", r1=0.01, rsi=50.0),
        _inst("B", "Tech", r1=0.03, rsi=None),
        _inst("C", "Tech", r1=0.02, rsi=70.0),
    ]
    aggs = aggregate_sectors(members, spx_return_30d=None)
    assert len(aggs) == 1
    agg = aggs[0]
    assert agg.avg_return_1d == pytest.approx(0.02)
    assert agg.median_rsi_14 is None
    # 1 of 3 missing == 33.3% > 30% threshold -> NULL even though 2 present.


def test_null_policy_boundary_30_pct_allows_metric() -> None:
    # 10 members, 3 missing (30% exactly, not > 30%) -> metric computed.
    members = [_inst(f"S{i}", "Energy", rsi=50.0 + i) for i in range(7)] + [
        _inst(f"M{i}", "Energy", rsi=None) for i in range(3)
    ]
    aggs = aggregate_sectors(members, spx_return_30d=None)
    assert aggs[0].median_rsi_14 == pytest.approx(53.0)


def test_rank_determinism_with_ties() -> None:
    members = [
        _inst("A", "Tech", r30=0.10),
        _inst("B", "Energy", r30=0.10),
        _inst("C", "Util", r30=0.05),
        _inst("D", "NoData", r30=None),
    ]
    aggs = aggregate_sectors(members, spx_return_30d=0.02)
    by_sector = {a.sector: a for a in aggs}
    # Tech and Energy tie on rel_strength 0.08 -> both DENSE_RANK 1.
    assert by_sector["Tech"].rotation_rank == 1
    assert by_sector["Energy"].rotation_rank == 1
    assert by_sector["Util"].rotation_rank == 2
    assert by_sector["NoData"].rel_strength_spx_30d is None
    assert by_sector["NoData"].rotation_rank is None


def test_rel_strength_null_without_spx() -> None:
    aggs = aggregate_sectors([_inst("A", "Tech", r30=0.10)], spx_return_30d=None)
    assert aggs[0].avg_return_30d == pytest.approx(0.10)
    assert aggs[0].rel_strength_spx_30d is None
    assert aggs[0].rotation_rank is None


def test_top_contributors_deterministic_order() -> None:
    members = [
        _inst("ZZZ", "Tech", r1=0.05),
        _inst("AAA", "Tech", r1=0.05),
        _inst("MMM", "Tech", r1=0.07),
        _inst("NNN", "Tech", r1=0.01),
        _inst("XXX", "Tech", r1=None),
    ]
    aggs = aggregate_sectors(members, spx_return_30d=None)
    contributors = aggs[0].top_contributors
    assert [c["symbol"] for c in contributors] == ["MMM", "AAA", "ZZZ"]
    assert contributors[0]["return_1d"] == pytest.approx(0.07)


@pytest.mark.asyncio
async def test_precondition_fails_without_indicator_rows() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(
        side_effect=[
            date(2026, 6, 10),  # resolve_target_trade_date
            0,  # indicator row count
        ],
    )
    worker = SectorAggregationWorker(database_url="postgresql://unused/unused")

    with pytest.raises(RuntimeError, match="Precondition failed"):
        await worker.execute(conn, date(2026, 6, 10), dry_run=False)


@pytest.mark.asyncio
async def test_upsert_idempotency_same_payload_twice() -> None:
    """Two runs over identical inputs produce identical upsert parameters."""
    members = [
        _inst("A", "Tech", r1=0.01, r5=0.02, r30=0.10, rsi=55.0, above50=True, vr=1.2),
    ]
    first = aggregate_sectors(members, spx_return_30d=0.04)
    second = aggregate_sectors(members, spx_return_30d=0.04)
    assert first == second
