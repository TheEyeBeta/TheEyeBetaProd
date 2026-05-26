"""Walk-forward window tests."""

from __future__ import annotations

from datetime import date

import pytest

from backtest_engine.walk_forward import WalkForwardConfig, iter_windows


@pytest.mark.unit
def test_walk_forward_disabled_returns_single_window() -> None:
    """walk_forward=false runs one full-span window."""
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    windows = iter_windows(start, end, WalkForwardConfig(enabled=False))
    assert len(windows) == 1
    assert windows[0].test_start == start
    assert windows[0].test_end == end


@pytest.mark.unit
def test_walk_forward_default_produces_multiple_folds() -> None:
    """12mo train / 3mo test / 1mo advance yields multiple test windows in one year."""
    start = date(2023, 1, 1)
    end = date(2024, 12, 31)
    windows = iter_windows(start, end, WalkForwardConfig())
    assert len(windows) >= 2
