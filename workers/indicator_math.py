"""Technical indicator math for canonical daily compute."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl

COMPUTE_VERSION = "theeyebeta_indicator_v1"
MIN_HISTORY_BARS = 200


@dataclass(slots=True, frozen=True)
class IndicatorRow:
    """One instrument's indicator values for a target date."""

    instrument_id: int
    ticker_id: int
    target_date: date
    sma_10: float | None
    sma_50: float | None
    sma_200: float | None
    ema_10: float | None
    ema_50: float | None
    ema_200: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    roc_10: float | None
    roc_20: float | None
    golden_cross_sma: bool
    death_cross_sma: bool
    momentum_rank_12_1: float | None = None


def _safe_float(value: float | int | None) -> float | None:
    """Normalize numeric values; map non-finite to None."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:  # noqa: PLR1714
        return None
    return numeric


def compute_indicators(
    prices: list[tuple[date, float, float, float, int]],
    *,
    instrument_id: int,
    ticker_id: int,
    target_date: date,
) -> IndicatorRow | None:
    """Compute indicator columns from ascending daily price rows."""
    if len(prices) < MIN_HISTORY_BARS:
        return None

    frame = pl.DataFrame(
        {
            "date": [row[0] for row in prices],
            "close": [float(row[1]) for row in prices],
            "high": [float(row[2]) for row in prices],
            "low": [float(row[3]) for row in prices],
            "volume": [int(row[4]) for row in prices],
        },
    ).sort("date")

    latest = frame["date"][-1]
    if latest != target_date:
        return None

    closes = frame["close"].cast(pl.Float64)
    sma_10 = _safe_float(closes.rolling_mean(window_size=10, min_samples=10).tail(1).item())
    sma_50 = _safe_float(closes.rolling_mean(window_size=50, min_samples=50).tail(1).item())
    sma_200 = _safe_float(closes.rolling_mean(window_size=200, min_samples=200).tail(1).item())

    ema_10 = _safe_float(closes.ewm_mean(span=10, adjust=False).tail(1).item())
    ema_50 = _safe_float(closes.ewm_mean(span=50, adjust=False).tail(1).item())
    ema_200 = _safe_float(closes.ewm_mean(span=200, adjust=False).tail(1).item())
    ema_12 = _safe_float(closes.ewm_mean(span=12, adjust=False).tail(1).item())
    ema_26 = _safe_float(closes.ewm_mean(span=26, adjust=False).tail(1).item())

    delta = closes.diff()
    gains = delta.clip(lower_bound=0.0)
    losses = (-delta).clip(lower_bound=0.0)
    avg_gain = gains.rolling_mean(window_size=14, min_samples=14)
    avg_loss = losses.rolling_mean(window_size=14, min_samples=14)
    rs = avg_gain / avg_loss
    rsi_14 = _safe_float((100 - (100 / (1 + rs))).tail(1).item())

    macd = macd_signal = macd_hist = None
    if len(closes) >= 26:
        macd_series = closes.ewm_mean(span=12, adjust=False) - closes.ewm_mean(
            span=26,
            adjust=False,
        )
        macd_signal_series = macd_series.ewm_mean(span=9, adjust=False)
        macd_hist_series = macd_series - macd_signal_series
        macd = _safe_float(macd_series.tail(1).item())
        macd_signal = _safe_float(macd_signal_series.tail(1).item())
        macd_hist = _safe_float(macd_hist_series.tail(1).item())

    roc_10 = _safe_float(
        ((closes / closes.shift(10) - 1) * 100).tail(1).item() if len(closes) >= 11 else None,
    )
    roc_20 = _safe_float(
        ((closes / closes.shift(20) - 1) * 100).tail(1).item() if len(closes) >= 21 else None,
    )

    golden_cross = False
    death_cross = False
    if len(closes) >= 201:
        sma50_series = closes.rolling_mean(window_size=50, min_samples=50)
        sma200_series = closes.rolling_mean(window_size=200, min_samples=200)
        prev_sma50 = _safe_float(sma50_series.tail(2).head(1).item())
        prev_sma200 = _safe_float(sma200_series.tail(2).head(1).item())
        if (
            prev_sma50 is not None
            and prev_sma200 is not None
            and sma_50 is not None
            and sma_200 is not None
            and prev_sma50 < prev_sma200
            and sma_50 > sma_200
        ):
            golden_cross = True
        elif (
            prev_sma50 is not None
            and prev_sma200 is not None
            and sma_50 is not None
            and sma_200 is not None
            and prev_sma50 > prev_sma200
            and sma_50 < sma_200
        ):
            death_cross = True

    return IndicatorRow(
        instrument_id=instrument_id,
        ticker_id=ticker_id,
        target_date=target_date,
        sma_10=sma_10,
        sma_50=sma_50,
        sma_200=sma_200,
        ema_10=ema_10,
        ema_50=ema_50,
        ema_200=ema_200,
        ema_12=ema_12,
        ema_26=ema_26,
        rsi_14=rsi_14,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        roc_10=roc_10,
        roc_20=roc_20,
        golden_cross_sma=golden_cross,
        death_cross_sma=death_cross,
    )


def indicator_row_to_bind(
    row: IndicatorRow,
) -> tuple[object, ...]:
    """Return executemany bind tuple for ``theeyebeta.ind_technical_daily``."""
    now = datetime.now(UTC)
    return (
        row.instrument_id,
        row.target_date,
        row.ticker_id,
        row.sma_10,
        row.sma_50,
        row.sma_200,
        row.ema_10,
        row.ema_50,
        row.ema_200,
        row.rsi_14,
        row.macd,
        row.macd_signal,
        row.macd_hist,
        row.roc_10,
        row.roc_20,
        row.golden_cross_sma,
        row.death_cross_sma,
        row.target_date,
        now,
        "close",
        COMPUTE_VERSION,
        row.ema_12,
        row.ema_26,
        row.momentum_rank_12_1,
    )
