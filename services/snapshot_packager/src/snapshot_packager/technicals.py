"""Technical indicator computation using Polars window functions.

All indicators are computed per-instrument via ``.over("instrument_id")``,
so the entire universe can be processed in a single vectorised pass.
"""

from __future__ import annotations

import polars as pl


def add_technicals(bars: pl.DataFrame) -> pl.DataFrame:
    """Append technical indicator columns to a sorted OHLCV DataFrame.

    Computes indicators per-instrument using Polars window functions.
    Prices used:
      - ``adj_close`` for trend/momentum indicators (SMA, Z-score, Bollinger)
        because it is corporate-action robust across the 250-bar window.
      - ``close`` for ATR and RSI because they model intraday price action.

    Args:
        bars: DataFrame sorted by ``(instrument_id, ts)`` with columns
            ``instrument_id``, ``ts``, ``open``, ``high``, ``low``,
            ``close``, ``adj_close``, ``volume``.

    Returns:
        Input DataFrame with additional columns:
        ``sma20``, ``sma50``, ``sma200``, ``atr14``, ``zscore20``,
        ``bb_upper20_2``, ``bb_lower20_2``, ``rsi14``.
        Intermediate columns are dropped.
    """
    ic = pl.col("instrument_id")
    ac = pl.col("adj_close")
    c = pl.col("close")
    h = pl.col("high")
    lo = pl.col("low")
    prev_c = c.shift(1).over(ic)

    # True range = max(H-L, |H-prev_C|, |L-prev_C|)
    tr = pl.max_horizontal([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()])

    # Close delta per instrument (for RSI)
    delta = c.diff().over(ic)
    gain = pl.when(delta > 0).then(delta).otherwise(0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0)

    out = (
        bars.with_columns(
            [
                tr.alias("_tr"),
                ac.rolling_mean(20).over(ic).alias("sma20"),
                ac.rolling_mean(50).over(ic).alias("sma50"),
                ac.rolling_mean(200).over(ic).alias("sma200"),
                ac.rolling_std(20).over(ic).alias("_std20"),
                gain.alias("_gain"),
                loss.alias("_loss"),
            ]
        )
        .with_columns(
            [
                pl.col("_tr").rolling_mean(14).over(ic).alias("atr14"),
                ((ac - pl.col("sma20")) / pl.col("_std20")).alias("zscore20"),
                (pl.col("sma20") + 2 * pl.col("_std20")).alias("bb_upper20_2"),
                (pl.col("sma20") - 2 * pl.col("_std20")).alias("bb_lower20_2"),
                pl.col("_gain").rolling_mean(14).over(ic).alias("_avg_gain"),
                pl.col("_loss").rolling_mean(14).over(ic).alias("_avg_loss"),
            ]
        )
        .with_columns(
            [
                (
                    100
                    - (100 / (1 + pl.col("_avg_gain") / pl.col("_avg_loss")))
                ).alias("rsi14"),
            ]
        )
        .drop(["_tr", "_std20", "_gain", "_loss", "_avg_gain", "_avg_loss"])
    )
    return out
