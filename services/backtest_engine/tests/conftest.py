"""pytest fixtures for backtest_engine."""

from __future__ import annotations

import sys
import types
from enum import IntEnum
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _install_bt_stub() -> None:
    """Minimal bt stub when the C++ extension is not built."""
    if "zinc_native._zinc_bt" in sys.modules:
        return

    class Side(IntEnum):
        Buy = 0
        Sell = 1

    class Decision:
        def __init__(self, symbol_index: int = -1, target_weight: float = 0.0) -> None:
            self.symbol_index = symbol_index
            self.target_weight = target_weight

    class Snapshot:
        def __init__(
            self,
            trade_date: str,
            day_index: int,
            symbol_names: list[str],
            closes: list[float] | None = None,
        ) -> None:
            self.trade_date = trade_date
            self.day_index = day_index
            self.symbol_names = symbol_names
            n = len(symbol_names)
            if closes is not None:
                self.close = np.asarray(closes, dtype=np.float64)
            else:
                growth = 1.0001**day_index
                self.close = np.full(n, 100.0 * growth)
            self.atr14 = np.ones(n)
            self.adv = np.full(n, 1e9)
            self.volume = np.full(n, 1_000_000, dtype=np.int64)

    class Metrics:
        def __init__(
            self,
            total_return: float = 0.0,
            sharpe_ratio: float = 0.0,
            max_drawdown: float = 0.0,
            turnover: float = 0.0,
        ) -> None:
            self.total_return = total_return
            self.sharpe_ratio = sharpe_ratio
            self.max_drawdown = max_drawdown
            self.turnover = turnover

    class Execution:
        def __init__(
            self,
            trade_date: str,
            symbol: str,
            side: Side,
            quantity: float,
            price: float,
        ) -> None:
            self.trade_date = trade_date
            self.symbol = symbol
            self.side = side
            self.quantity = quantity
            self.price = price
            self.slippage_bps = 0.0
            self.notional = abs(quantity * price)

    class Result:
        def __init__(self) -> None:
            self.daily_pnl: list[float] = []
            self.drawdown_series: list[float] = []
            self.executions: list[Execution] = []
            self.metrics = Metrics()

    class SlippageModel:
        def __init__(self, formula=None) -> None:  # noqa: ANN001
            self._formula = formula

    class Engine:
        def __init__(
            self,
            strategy_id: str,
            start_date: str,
            end_date: str,
            universe: list[str],
            slippage_model: SlippageModel,
        ) -> None:
            self._strategy_id = strategy_id
            self._start = start_date
            self._end = end_date
            self._universe = universe
            self._strategy = None
            self._parquet = ""
            self._slippage_model = slippage_model
            self._price_by_date: dict[str, list[float]] = {}

        def set_parquet_path(self, path: str) -> None:
            self._parquet = path

        def set_strategy(self, strategy) -> None:  # noqa: ANN001
            self._strategy = strategy

        def run(self) -> Result:
            result = Result()
            if not self._universe or self._start > self._end or not self._strategy:
                return result
            from datetime import date, timedelta

            start = date.fromisoformat(self._start)
            end = date.fromisoformat(self._end)
            cash = 1.0
            shares: dict[str, float] = {sym: 0.0 for sym in self._universe}
            prev_equity = 1.0
            peak = 1.0
            day = start
            idx = 0
            while day <= end:
                closes = self._price_by_date.get(day.isoformat())
                snap = Snapshot(
                    day.isoformat(),
                    idx,
                    self._universe,
                    closes=closes,
                )
                decision = self._strategy(snap)
                sym_idx = max(0, min(decision.symbol_index, len(self._universe) - 1))
                symbol = self._universe[sym_idx]
                close = float(snap.close[sym_idx])
                if close <= 0:
                    day += timedelta(days=1)
                    idx += 1
                    continue
                position = shares[symbol]
                equity = cash + sum(
                    shares[s] * float(snap.close[i]) for i, s in enumerate(self._universe)
                )
                target_value = equity * max(0.0, min(1.0, decision.target_weight))
                current_value = position * close
                trade_value = target_value - current_value
                if abs(trade_value) > 1e-12:
                    trade_shares = trade_value / close
                    is_buy = trade_shares > 0
                    slip = 0.0
                    if self._slippage_model._formula is not None:
                        slip = float(
                            self._slippage_model._formula(
                                float(snap.atr14[sym_idx]),
                                trade_shares,
                            ),
                        )
                    exec_price = close * (1.0 + slip if is_buy else 1.0 - slip)
                    cash -= trade_shares * exec_price
                    shares[symbol] += trade_shares
                    result.executions.append(
                        Execution(
                            day.isoformat(),
                            symbol,
                            Side.Buy if is_buy else Side.Sell,
                            abs(trade_shares),
                            exec_price,
                        ),
                    )
                equity = cash + sum(
                    shares[s] * float(snap.close[i]) for i, s in enumerate(self._universe)
                )
                pnl = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
                result.daily_pnl.append(pnl)
                peak = max(peak, equity)
                dd = (peak - equity) / peak if peak > 0 else 0.0
                result.drawdown_series.append(dd)
                prev_equity = equity
                day += timedelta(days=1)
                idx += 1
            if result.daily_pnl:
                result.metrics = Metrics(
                    total_return=sum(result.daily_pnl),
                    sharpe_ratio=1.0,
                    max_drawdown=max(result.drawdown_series),
                    turnover=float(len(result.executions)) * 0.1,
                )
            return result

    stub = types.ModuleType("zinc_native.bt")
    stub.Side = Side
    stub.Decision = Decision
    stub.Snapshot = Snapshot
    stub.Metrics = Metrics
    stub.Execution = Execution
    stub.Result = Result
    stub.SlippageModel = SlippageModel
    stub.Engine = Engine
    sys.modules["zinc_native._zinc_bt"] = stub
    sys.modules["zinc_native.bt"] = stub


_install_bt_stub()
