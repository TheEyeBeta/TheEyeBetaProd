"""Unit tests for market-cap universe helpers and workers."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from workers.market_cap_providers import (
    CAP_THRESHOLD_USD,
    CapSnapshot,
    classify_cap_crossings,
    reference_ticker_variants,
    symbols_above_threshold,
)
from workers.market_cap_threshold_worker import MarketCapThresholdWorker


def test_reference_ticker_variants_for_class_shares() -> None:
    assert reference_ticker_variants("BF-B") == ["BF-B", "BF.B"]
    assert reference_ticker_variants("BRK.B") == ["BRK.B", "BRK-B"]


def test_classify_crosses_up_from_below() -> None:
    today = {
        "NEWCO": CapSnapshot(symbol="NEWCO", market_cap=600_000_000.0),
    }
    yesterday = {
        "NEWCO": CapSnapshot(symbol="NEWCO", market_cap=400_000_000.0),
    }
    crossings = classify_cap_crossings(today, yesterday, threshold=CAP_THRESHOLD_USD)
    assert len(crossings) == 1
    assert crossings[0].event_type == "CROSSED_UP"
    assert crossings[0].symbol == "NEWCO"


def test_classify_crosses_down_from_above() -> None:
    today = {
        "OLDCO": CapSnapshot(symbol="OLDCO", market_cap=400_000_000.0),
    }
    yesterday = {
        "OLDCO": CapSnapshot(symbol="OLDCO", market_cap=600_000_000.0),
    }
    crossings = classify_cap_crossings(today, yesterday, threshold=CAP_THRESHOLD_USD)
    assert len(crossings) == 1
    assert crossings[0].event_type == "CROSSED_DOWN"


def test_classify_ignores_stable_names() -> None:
    today = {"BIG": CapSnapshot(symbol="BIG", market_cap=900_000_000.0)}
    yesterday = {"BIG": CapSnapshot(symbol="BIG", market_cap=850_000_000.0)}
    assert classify_cap_crossings(today, yesterday, threshold=CAP_THRESHOLD_USD) == []


def test_symbols_above_threshold_sorted() -> None:
    snaps = {
        "ZZZ": CapSnapshot(symbol="ZZZ", market_cap=600_000_000.0),
        "AAA": CapSnapshot(symbol="AAA", market_cap=700_000_000.0),
        "TINY": CapSnapshot(symbol="TINY", market_cap=10_000_000.0),
    }
    assert symbols_above_threshold(snaps) == ["AAA", "ZZZ"]


async def test_threshold_worker_dry_run_reports_crossings() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[date(2026, 6, 12), date(2026, 6, 11)])
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {"symbol": "UPCO", "market_cap": 600_000_000, "instrument_id": 1},
            ],
            [
                {"symbol": "UPCO", "market_cap": 400_000_000, "instrument_id": 1},
            ],
        ],
    )

    result = await MarketCapThresholdWorker(
        database_url="postgresql://unused/unused",
    ).execute(conn, date(2026, 6, 12), dry_run=True)

    assert result.metadata["crossed_up"] == 1
    assert result.metadata["crossed_down"] == 0
    conn.execute.assert_not_awaited()


async def test_threshold_worker_raises_without_today_snapshot() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[date(2026, 6, 12), date(2026, 6, 11)])
    conn.fetch = AsyncMock(side_effect=[[], [{"symbol": "X", "market_cap": 1, "instrument_id": 1}]])

    with pytest.raises(RuntimeError, match="market_cap_daily"):
        await MarketCapThresholdWorker(
            database_url="postgresql://unused/unused",
        ).execute(conn, date(2026, 6, 12), dry_run=False)
