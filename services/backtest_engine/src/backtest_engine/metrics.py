"""Extended performance metrics beyond zinc_native.bt summary fields."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BacktestMetrics:
    """Eight metrics persisted to ``backtest_results``."""

    sharpe: float
    sortino: float
    calmar: float
    max_dd: float
    hit_rate: float
    avg_win: float
    avg_loss: float
    turnover: float

    def as_rows(self) -> list[tuple[str, float]]:
        """Return (metric, value) pairs for DB insert."""
        return [
            ("sharpe", self.sharpe),
            ("sortino", self.sortino),
            ("calmar", self.calmar),
            ("max_dd", self.max_dd),
            ("hit_rate", self.hit_rate),
            ("avg_win", self.avg_win),
            ("avg_loss", self.avg_loss),
            ("turnover", self.turnover),
        ]


def compute_metrics(
    daily_pnl: list[float] | np.ndarray,
    *,
    max_drawdown: float,
    turnover: float,
    trading_days_per_year: int = 252,
) -> BacktestMetrics:
    """Derive acceptance metrics from daily PnL and engine aggregates."""
    pnl = np.asarray(daily_pnl, dtype=np.float64)
    if pnl.size == 0:
        return BacktestMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, turnover)

    mean_pnl = float(np.mean(pnl))
    std_pnl = float(np.std(pnl, ddof=1)) if pnl.size > 1 else 0.0
    scale = math.sqrt(trading_days_per_year)
    sharpe = (mean_pnl / std_pnl * scale) if std_pnl > 0 else 0.0

    downside = pnl[pnl < 0]
    downside_std = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
    sortino = (mean_pnl / downside_std * scale) if downside_std > 0 else 0.0

    equity = np.cumsum(np.insert(pnl, 0, 1.0))
    years = max(pnl.size / trading_days_per_year, 1e-9)
    total_return = float(equity[-1] - 1.0)
    annualized = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    calmar = annualized / max_drawdown if max_drawdown > 1e-12 else 0.0

    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    hit_rate = float(wins.size / pnl.size)
    avg_win = float(np.mean(wins)) if wins.size else 0.0
    avg_loss = float(np.mean(losses)) if losses.size else 0.0

    return BacktestMetrics(
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_dd=max_drawdown,
        hit_rate=hit_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        turnover=turnover,
    )
