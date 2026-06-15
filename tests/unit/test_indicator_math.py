"""Unit tests for indicator math."""

from __future__ import annotations

from datetime import date, timedelta

from workers.indicator_math import compute_indicators


def _price_series(
    start: date, days: int, base: float = 100.0
) -> list[tuple[date, float, float, float, int]]:
    rows: list[tuple[date, float, float, float, int]] = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        price = base + offset * 0.1
        rows.append((d, price, price + 1, price - 1, 1_000_000))
    return rows


def test_compute_indicators_produces_row() -> None:
    start = date(2025, 1, 1)
    prices = _price_series(start, 220)
    target = prices[-1][0]
    row = compute_indicators(
        prices,
        instrument_id=1,
        ticker_id=10,
        target_date=target,
    )
    assert row is not None
    assert row.sma_200 is not None
    assert row.rsi_14 is not None


def test_compute_indicators_insufficient_history() -> None:
    start = date(2025, 1, 1)
    prices = _price_series(start, 50)
    assert (
        compute_indicators(
            prices,
            instrument_id=1,
            ticker_id=10,
            target_date=prices[-1][0],
        )
        is None
    )
