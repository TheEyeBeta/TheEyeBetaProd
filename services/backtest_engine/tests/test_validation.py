"""P-BT-02 Phase 10 validation: look-ahead, survivorship, live PnL reconciliation."""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backtest_engine.decisions import DecisionBook, make_strategy_callback  # noqa: E402
from backtest_engine.reconcile import assert_live_week_reconciles  # noqa: E402
from backtest_engine.runner import _run_engine  # noqa: E402
from backtest_engine.universe import is_symbol_tradable  # noqa: E402
from backtest_engine.validation import (  # noqa: E402
    LiveFill,
    LookAheadViolation,
    assert_decision_book_no_lookahead,
    assert_pnl_within_bps,
    assert_slippage_realistic,
    assert_snapshot_date,
    guard_decision_callback,
)

pytestmark = pytest.mark.validation


@pytest.mark.unit
def test_no_lookahead_raises_when_t_plus_one_snapshot_injected() -> None:
    """Injecting a T+1 snapshot into the date-T pipeline raises LookAheadViolation."""
    pipeline_date = "2024-01-01"
    injected_snapshot_date = "2024-01-02"
    with pytest.raises(LookAheadViolation, match="look-ahead"):
        assert_snapshot_date(injected_snapshot_date, pipeline_date)


@pytest.mark.unit
def test_no_lookahead_raises_when_future_decision_in_book() -> None:
    """Decision book weights for T+1 while simulating T raises LookAheadViolation."""
    book = DecisionBook()
    book.by_date["2024-01-02"] = {"DELIST": 1.0}
    with pytest.raises(LookAheadViolation, match="look-ahead"):
        assert_decision_book_no_lookahead(book, "2024-01-01")


@pytest.mark.unit
def test_no_lookahead_guard_blocks_engine_run_with_future_decisions() -> None:
    """Guarded engine callback rejects future-dated decisions before C++ run."""
    book = DecisionBook()
    book.by_date["2024-01-02"] = {"SPY": 1.0}
    callback = guard_decision_callback(
        book,
        make_strategy_callback(book, max_positions=1),
    )
    with pytest.raises(LookAheadViolation):
        callback("2024-01-01", ["SPY"], 0)


@pytest.mark.unit
def test_survivorship_delisted_instrument_in_universe_pre_delist_only() -> None:
    """Delisted names are tradable before ``delisted_at`` and excluded after."""
    listed = date(2020, 1, 1)
    delisted = date(2024, 6, 30)
    assert is_symbol_tradable(date(2024, 6, 1), listed_at=listed, delisted_at=delisted)
    assert is_symbol_tradable(date(2024, 6, 29), listed_at=listed, delisted_at=delisted)
    assert not is_symbol_tradable(date(2024, 7, 1), listed_at=listed, delisted_at=delisted)


@pytest.mark.unit
def test_survivorship_delisting_liquidates_at_last_available_price() -> None:
    """Pre-delisting buy then missing bars forces exit at last close (liquidation)."""
    symbol = "GONE"
    start = date(2024, 1, 1)
    delist = date(2024, 1, 5)
    rows: list[dict[str, object]] = []
    day = start
    price = 100.0
    while day < delist:
        rows.append(
            {
                "trade_date": day.isoformat(),
                "symbol": symbol,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1_000_000,
                "atr14": 2.0,
                "adv": 1.0e9,
            },
        )
        day += timedelta(days=1)
        price += 1.0

    book = DecisionBook()
    book.by_date[start.isoformat()] = {symbol: 1.0}
    book.by_date[(start + timedelta(days=1)).isoformat()] = {symbol: 1.0}
    for off in range(2, 5):
        book.by_date[(start + timedelta(days=off)).isoformat()] = {symbol: 0.0}

    price_map = {row["trade_date"]: [float(row["close"])] for row in rows}  # type: ignore[index]
    with tempfile.TemporaryDirectory() as tmp:
        parquet_path = Path(tmp) / "delist.parquet"
        pq.write_table(pa.Table.from_pylist(rows), parquet_path)
        callback = make_strategy_callback(book, max_positions=1)
        result = _run_engine(
            "survivorship",
            start,
            date(2024, 1, 10),
            [symbol],
            parquet_path,
            callback,
            prices_by_date=price_map,
        )

    assert len(result.executions) >= 1
    assert any(float(ex.price) > 0 for ex in result.executions)
    last_price = float(result.executions[-1].price)
    assert last_price == pytest.approx(104.0, rel=0.05)


@pytest.mark.unit
def test_slippage_model_is_positive_and_realistic() -> None:
    """Default slippage is non-zero and within a plausible range for liquid US names."""
    assert_slippage_realistic(atr=2.5, participation=500.0)


@pytest.mark.unit
def test_pnl_reconciliation_live_week_within_one_bp() -> None:
    """Replay a live trading week; engine PnL matches live within 1 bp net of slippage."""
    prices = {
        "2024-03-04": 100.0,
        "2024-03-05": 101.0,
        "2024-03-06": 100.5,
        "2024-03-07": 102.0,
        "2024-03-08": 101.5,
    }
    fills = [
        LiveFill("2024-03-04", "SPY", "buy", 1.0, 100.0, slippage_bps=5.0),
        LiveFill("2024-03-08", "SPY", "sell", 1.0, 101.5, slippage_bps=5.0),
    ]
    assert_live_week_reconciles(fills, prices_by_date=prices, tolerance_bps=1.0)


@pytest.mark.unit
def test_pnl_reconciliation_helper_tolerates_sub_bp_delta() -> None:
    """Sanity check the bps tolerance helper accepts sub-1bp deltas."""
    assert_pnl_within_bps(0.0100, 0.01000005, tolerance_bps=1.0)
