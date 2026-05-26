"""Walk-forward train/test window generation."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class WalkForwardConfig:
    """Rolling walk-forward parameters stored in ``backtest_runs.config``."""

    enabled: bool = True
    train_months: int = 12
    test_months: int = 3
    advance_months: int = 1


@dataclass(frozen=True)
class WalkForwardWindow:
    """One train/test fold."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date


def parse_walk_forward(config: dict) -> WalkForwardConfig:
    """Parse walk-forward settings from run config JSON."""
    wf = config.get("walk_forward") or {}
    if isinstance(wf, bool):
        return WalkForwardConfig(enabled=wf)
    return WalkForwardConfig(
        enabled=bool(wf.get("enabled", True)),
        train_months=int(wf.get("train_months", 12)),
        test_months=int(wf.get("test_months", 3)),
        advance_months=int(wf.get("advance_months", 1)),
    )


def _add_months(value: date, months: int) -> date:
    """Add calendar months preserving day-of-month when possible."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(value.day, last_day))


def iter_windows(
    start: date,
    end: date,
    wf: WalkForwardConfig,
) -> list[WalkForwardWindow]:
    """Build rolling test windows; train span is metadata for re-decision mode."""
    if not wf.enabled:
        return [
            WalkForwardWindow(
                train_start=start,
                train_end=end,
                test_start=start,
                test_end=end,
            ),
        ]

    windows: list[WalkForwardWindow] = []
    test_start = _add_months(start, wf.train_months)
    while test_start <= end:
        test_end = min(_add_months(test_start, wf.test_months) - timedelta(days=1), end)
        if test_start > test_end:
            break
        train_start = _add_months(test_start, -wf.train_months)
        train_end = test_start - timedelta(days=1)
        windows.append(
            WalkForwardWindow(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ),
        )
        test_start = _add_months(test_start, wf.advance_months)

    return windows
