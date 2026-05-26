"""Unit tests for extended metrics."""

from __future__ import annotations

import pytest

from backtest_engine.metrics import compute_metrics


@pytest.mark.unit
def test_compute_metrics_returns_eight_fields() -> None:
    """Acceptance metrics include sharpe/sortino/calmar and hit-rate stats."""
    pnl = [0.01, -0.005, 0.002, 0.003, -0.001, 0.004]
    metrics = compute_metrics(pnl, max_drawdown=0.02, turnover=1.2)
    rows = dict(metrics.as_rows())
    assert len(rows) == 8
    assert set(rows) == {
        "sharpe",
        "sortino",
        "calmar",
        "max_dd",
        "hit_rate",
        "avg_win",
        "avg_loss",
        "turnover",
    }
    assert rows["turnover"] == pytest.approx(1.2)
    assert rows["max_dd"] == pytest.approx(0.02)
