"""Backtest correctness guards — look-ahead, survivorship, PnL reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from backtest_engine.decisions import DecisionBook

log = structlog.get_logger()


class LookAheadViolation(RuntimeError):  # noqa: N818 — domain name from P-BT-02 spec
    """Raised when the simulation pipeline reads data from a future trade date."""


def assert_snapshot_date(snapshot_trade_date: str, pipeline_date: str) -> None:
    """Ensure the engine snapshot matches the pipeline date (no T+1 injection).

    Args:
        snapshot_trade_date: ``Snapshot.trade_date`` observed by the strategy.
        pipeline_date: Calendar date currently being simulated (ISO).

    Raises:
        LookAheadViolation: When ``snapshot_trade_date`` is after ``pipeline_date``.
    """
    if snapshot_trade_date > pipeline_date:
        msg = (
            f"look-ahead: snapshot trade_date {snapshot_trade_date!r} is after "
            f"pipeline date {pipeline_date!r}"
        )
        log.warning("look_ahead_snapshot", snapshot=snapshot_trade_date, pipeline=pipeline_date)
        raise LookAheadViolation(msg)


def assert_decision_book_no_lookahead(book: DecisionBook, pipeline_date: str) -> None:
    """Reject decision books that assign weights using future dates.

    Args:
        book: Decision weights keyed by trade date.
        pipeline_date: Calendar date currently being simulated (ISO).

    Raises:
        LookAheadViolation: When any book key is after ``pipeline_date``.
    """
    future_dates = sorted(d for d in book.by_date if d > pipeline_date)
    if future_dates:
        msg = (
            f"look-ahead: decision book contains future date(s) {future_dates!r} "
            f"while simulating {pipeline_date!r}"
        )
        log.warning("look_ahead_decisions", future=future_dates, pipeline=pipeline_date)
        raise LookAheadViolation(msg)


def guard_decision_callback(
    book: DecisionBook,
    inner: Callable[[str, list[str], int], tuple[int, float]],
) -> Callable[[str, list[str], int], tuple[int, float]]:
    """Wrap a decision callback with look-ahead checks on every engine day."""

    def _guarded(trade_date: str, symbols: list[str], day_index: int) -> tuple[int, float]:
        assert_decision_book_no_lookahead(book, trade_date)
        return inner(trade_date, symbols, day_index)

    return _guarded


def guard_engine_strategy(
    book: DecisionBook,
    inner_strategy: Callable[[object], object],
) -> Callable[[object], object]:
    """Wrap the zinc_native strategy with per-day look-ahead checks on the decision book."""

    def _strategy(snapshot: object) -> object:
        trade_date = str(snapshot.trade_date)
        assert_decision_book_no_lookahead(book, trade_date)
        return inner_strategy(snapshot)

    return _strategy


@dataclass(frozen=True)
class LiveFill:
    """One live execution used for PnL reconciliation tests."""

    trade_date: str
    symbol: str
    side: str
    qty: float
    price: float
    slippage_bps: float = 0.0


def simulate_fractional_week(
    decision_callback: Callable[[str, list[str], int], tuple[int, float]],
    symbols: list[str],
    prices_by_date: dict[str, list[float]],
    slippage_fn: Callable[[float, float], float],
    *,
    atr14: float = 1.0,
) -> list[float]:
    """Independent fractional-equity simulator (mirrors ``zinc::bt::Engine`` logic)."""
    dates = sorted(prices_by_date)
    if not dates:
        return []
    cash = 1.0
    shares = {sym: 0.0 for sym in symbols}
    prev_equity = 1.0
    daily: list[float] = []
    for day_index, trade_date in enumerate(dates):
        closes = prices_by_date[trade_date]
        sym_idx, weight = decision_callback(trade_date, symbols, day_index)
        sym_idx = max(0, min(sym_idx, len(symbols) - 1))
        symbol = symbols[sym_idx]
        close = closes[sym_idx] if sym_idx < len(closes) else closes[0]
        weight = min(1.0, max(0.0, weight))
        equity = cash + sum(
            shares[s] * (closes[i] if i < len(closes) else closes[0])
            for i, s in enumerate(symbols)
        )
        target_value = equity * weight
        current_value = shares[symbol] * close
        trade_value = target_value - current_value
        if abs(trade_value) > 1e-12:
            trade_shares = trade_value / close
            slip = slippage_fn(atr14, trade_shares)
            exec_price = close * (1.0 + slip if trade_shares > 0 else 1.0 - slip)
            cash -= trade_shares * exec_price
            shares[symbol] += trade_shares
        equity = cash + sum(
            shares[s] * (closes[i] if i < len(closes) else closes[0])
            for i, s in enumerate(symbols)
        )
        pnl = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        daily.append(pnl)
        prev_equity = equity
    return daily


def engine_net_pnl(daily_pnl: list[float], *, initial_equity: float = 1.0) -> float:
    """Cumulative net return from engine daily PnL fractions."""
    equity = initial_equity
    for pnl in daily_pnl:
        equity *= 1.0 + float(pnl)
    return equity / initial_equity - 1.0


def assert_pnl_within_bps(
    live_return: float,
    engine_return: float,
    *,
    tolerance_bps: float = 1.0,
) -> None:
    """Assert engine replay matches live within ``tolerance_bps`` (net of slippage)."""
    tolerance = tolerance_bps * 1e-4
    delta = abs(engine_return - live_return)
    if delta > tolerance:
        msg = (
            f"PnL reconciliation failed: live={live_return:.8f} engine={engine_return:.8f} "
            f"delta={delta:.8f} tolerance={tolerance:.8f} ({tolerance_bps} bps)"
        )
        raise AssertionError(msg)


def slippage_fraction(atr: float, participation: float) -> float:
    """Default backtest slippage formula (matches ``runner._default_slippage``)."""
    return min(0.0005 * max(atr, 1.0) + 0.0001 * abs(participation), 0.02)


def assert_slippage_realistic(
    *,
    atr: float = 2.5,
    participation: float = 500.0,
    min_bps: float = 0.5,
    max_bps: float = 200.0,
) -> None:
    """Slippage must be positive and within a realistic band for liquid names."""
    fraction = slippage_fraction(atr, participation)
    bps = fraction * 10_000.0
    if fraction <= 0.0 or bps < min_bps or bps > max_bps:
        msg = f"unrealistic slippage: {bps:.2f} bps (fraction={fraction:.6f})"
        raise AssertionError(msg)
