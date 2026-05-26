"""Replay live trading weeks through the engine for PnL reconciliation."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backtest_engine.decisions import DecisionBook, make_strategy_callback
from backtest_engine.runner import _run_engine
from backtest_engine.validation import (
    LiveFill,
    assert_pnl_within_bps,
    engine_net_pnl,
    simulate_fractional_week,
    slippage_fraction,
)


def _write_week_parquet(
    path: Path,
    *,
    symbol: str,
    start: date,
    prices: list[float],
) -> None:
    """Write one symbol daily bars for a live replay week."""
    rows: list[dict[str, object]] = []
    day = start
    for close in prices:
        rows.append(
            {
                "trade_date": day.isoformat(),
                "symbol": symbol,
                "open": close,
                "high": close * 1.001,
                "low": close * 0.999,
                "close": close,
                "volume": 1_000_000,
                "atr14": 2.5,
                "adv": 1.0e9,
            },
        )
        day += timedelta(days=1)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _book_from_fills(fills: list[LiveFill], dates: list[str], symbol: str) -> DecisionBook:
    """Build a decision book from live fills with forward-filled weights."""
    book = DecisionBook()
    fills_by_date = {f.trade_date: f for f in fills}
    weight = 0.0
    for trade_date in dates:
        fill = fills_by_date.get(trade_date)
        if fill is not None:
            weight = 1.0 if fill.side.lower() == "buy" else 0.0
        book.by_date[trade_date] = {symbol: weight}
    return book


def replay_live_week(
    fills: list[LiveFill],
    *,
    prices_by_date: dict[str, float],
) -> tuple[float, float]:
    """Replay ``fills`` through the engine and return (live, engine) net returns.

    Args:
        fills: Chronological live executions for one symbol.
        prices_by_date: Closing prices for each trade date in the week.

    Returns:
        Tuple of (live_net_return, engine_net_return).
    """
    if not fills:
        return 0.0, 0.0

    symbol = fills[0].symbol
    dates = sorted(prices_by_date)
    start = date.fromisoformat(dates[0])
    end = date.fromisoformat(dates[-1])
    book = _book_from_fills(fills, dates, symbol)
    price_map = {d: [prices_by_date[d]] for d in dates}

    callback = make_strategy_callback(book, max_positions=1)
    live_daily = simulate_fractional_week(
        callback,
        [symbol],
        price_map,
        slippage_fraction,
        atr14=1.0,
    )
    live_ret = engine_net_pnl(live_daily)

    with tempfile.TemporaryDirectory() as tmp:
        parquet_path = Path(tmp) / "week.parquet"
        _write_week_parquet(
            parquet_path,
            symbol=symbol,
            start=start,
            prices=[prices_by_date[d] for d in dates],
        )
        result = _run_engine(
            "live_replay",
            start,
            end,
            [symbol],
            parquet_path,
            callback,
            prices_by_date=price_map,
        )

    engine_ret = engine_net_pnl([float(v) for v in result.daily_pnl])
    return live_ret, engine_ret


def assert_live_week_reconciles(
    fills: list[LiveFill],
    *,
    prices_by_date: dict[str, float],
    tolerance_bps: float = 1.0,
) -> None:
    """Replay a live week and assert engine PnL matches within ``tolerance_bps``."""
    live_ret, engine_ret = replay_live_week(fills, prices_by_date=prices_by_date)
    assert_pnl_within_bps(live_ret, engine_ret, tolerance_bps=tolerance_bps)
