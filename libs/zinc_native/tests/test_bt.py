"""pytest mirrors of cpp/tests/bt_engine_test.cpp."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import sys as _sys

import numpy as np
import pytest

pa = pytest.importorskip("pyarrow")
_zinc_bt = _sys.modules.get("zinc_native._zinc_bt")
if _zinc_bt is None:
    pytest.importorskip("zinc_native._zinc_bt", reason="C++ kernels not compiled — run make build-cpp")
elif not getattr(_zinc_bt, "__file__", None):
    pytest.skip("C++ kernels not compiled — zinc_native.bt is a Python stub", allow_module_level=True)
import pyarrow.parquet as pq  # noqa: E402

from zinc_native import bt

GROWTH_PER_DAY = 1.0001
BUY_HOLD_DAYS = 100
REFERENCE_TOTAL_RETURN = 0.009950330903168  # 1.0001^99 - 1


def _zero_slippage() -> bt.SlippageModel:
    return bt.SlippageModel(lambda _atr, _participation: 0.0)


def _write_daily_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


def _write_buy_hold_fixture(path: Path) -> None:
    rows: list[dict[str, object]] = []
    for day in range(BUY_HOLD_DAYS):
        month = 1 + day // 31
        day_of_month = 1 + day % 31
        trade_date = f"2024-{month:02d}-{day_of_month:02d}"
        close = 100.0 * (GROWTH_PER_DAY**day)
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": "SPY",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000_000,
                "atr14": 1.0,
                "adv": 1.0e9,
            }
        )
    _write_daily_parquet(path, rows)


def _sum_pnl(daily_pnl: np.ndarray | list[float]) -> float:
    return float(np.sum(np.asarray(daily_pnl, dtype=np.float64)))


class TestEngine:
    def test_happy_path_buy_and_hold_within_one_basis_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parquet_path = Path(tmp_dir) / "daily.parquet"
            _write_buy_hold_fixture(parquet_path)

            engine = bt.Engine(
                "buy_hold",
                "2024-01-01",
                "2024-12-31",
                ["SPY"],
                _zero_slippage(),
            )
            engine.set_parquet_path(str(parquet_path))
            engine.set_strategy(
                lambda _snapshot: bt.Decision(symbol_index=0, target_weight=1.0)
            )
            result = engine.run()

        assert len(result.daily_pnl) == BUY_HOLD_DAYS
        assert len(result.drawdown_series) == BUY_HOLD_DAYS
        assert len(result.executions) == 1
        total_from_pnl = _sum_pnl(result.daily_pnl)
        assert result.metrics.total_return == pytest.approx(REFERENCE_TOTAL_RETURN, abs=1e-4)
        assert total_from_pnl == pytest.approx(REFERENCE_TOTAL_RETURN, abs=1e-4)
        assert result.metrics.total_return == pytest.approx(total_from_pnl, abs=1e-10)
        assert result.metrics.max_drawdown == pytest.approx(0.0, abs=1e-12)

    def test_empty_and_invalid_input_returns_empty(self) -> None:
        engine = bt.Engine("noop", "2024-06-01", "2024-01-01", ["SPY"], _zero_slippage())
        engine.set_strategy(lambda _snapshot: bt.Decision())
        invalid_window = engine.run()
        assert len(invalid_window.daily_pnl) == 0

        missing_data = bt.Engine("noop", "2024-01-01", "2024-12-31", [], _zero_slippage())
        missing_data.set_strategy(lambda _snapshot: bt.Decision())
        empty_universe = missing_data.run()
        assert len(empty_universe.daily_pnl) == 0

    def test_single_trading_day_flat_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parquet_path = Path(tmp_dir) / "daily.parquet"
            _write_daily_parquet(
                parquet_path,
                [
                    {
                        "trade_date": "2024-01-01",
                        "symbol": "SPY",
                        "open": 50.0,
                        "high": 50.0,
                        "low": 50.0,
                        "close": 50.0,
                        "volume": 1000,
                        "atr14": 1.0,
                        "adv": 1.0e9,
                    }
                ],
            )

            engine = bt.Engine(
                "single",
                "2024-01-01",
                "2024-01-01",
                ["SPY"],
                _zero_slippage(),
            )
            engine.set_parquet_path(str(parquet_path))
            engine.set_strategy(
                lambda _snapshot: bt.Decision(symbol_index=0, target_weight=1.0)
            )
            result = engine.run()

        assert len(result.daily_pnl) == 1
        assert result.daily_pnl[0] == pytest.approx(0.0, abs=1e-12)
        assert result.metrics.total_return == pytest.approx(0.0, abs=1e-12)

    def test_random_prices_produce_finite_metrics(self) -> None:
        rng = np.random.default_rng(0x0B7123)
        rows: list[dict[str, object]] = []
        close = 100.0
        for day in range(60):
            close *= float(rng.lognormal(0.0, 0.01))
            rows.append(
                {
                    "trade_date": f"2024-01-{day + 1:02d}",
                    "symbol": "SPY",
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                    "atr14": 1.0,
                    "adv": 1.0e9,
                }
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            parquet_path = Path(tmp_dir) / "daily.parquet"
            _write_daily_parquet(parquet_path, rows)

            engine = bt.Engine(
                "random",
                "2024-01-01",
                "2024-03-31",
                ["SPY"],
                _zero_slippage(),
            )
            engine.set_parquet_path(str(parquet_path))
            engine.set_strategy(
                lambda snapshot: bt.Decision(
                    symbol_index=0,
                    target_weight=1.0,
                )
            )
            start = time.perf_counter()
            result = engine.run()
            elapsed_ms = (time.perf_counter() - start) * 1000.0

        assert len(result.daily_pnl) == len(rows)
        assert np.all(np.isfinite(np.asarray(result.daily_pnl)))
        assert np.isfinite(result.metrics.total_return)
        assert result.metrics.max_drawdown >= 0.0
        assert elapsed_ms < 5000.0

    def test_numerical_stability_against_reference_literal(self) -> None:
        literal_total_return = REFERENCE_TOTAL_RETURN
        with tempfile.TemporaryDirectory() as tmp_dir:
            parquet_path = Path(tmp_dir) / "daily.parquet"
            _write_buy_hold_fixture(parquet_path)

            engine = bt.Engine(
                "literal",
                "2024-01-01",
                "2024-12-31",
                ["SPY"],
                _zero_slippage(),
            )
            engine.set_parquet_path(str(parquet_path))
            engine.set_strategy(
                lambda _snapshot: bt.Decision(symbol_index=0, target_weight=1.0)
            )
            result = engine.run()

        assert result.metrics.total_return == pytest.approx(literal_total_return, abs=1e-4)
        assert _sum_pnl(result.daily_pnl) == pytest.approx(literal_total_return, abs=1e-4)
