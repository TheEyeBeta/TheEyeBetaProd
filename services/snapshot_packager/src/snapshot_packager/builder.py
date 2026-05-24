"""Snapshot builder: queries the DB and assembles a Snapshot object."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import polars as pl
import psycopg
import structlog

from zinc_schemas.snapshot import (
    SCHEMA_VERSION,
    PriceBlock,
    Snapshot,
    TechnicalsBlock,
    UniverseEntry,
)

from .technicals import add_technicals

log = structlog.get_logger()

# Minimum bars to fetch per instrument — must exceed the longest indicator window
# (SMA200 = 200 bars) with margin.
WINDOW_BARS = 250


async def build_snapshot(
    conn: psycopg.AsyncConnection,  # type: ignore[type-arg]
    market: str,
    trade_date: date,
) -> Snapshot:
    """Build a complete Snapshot for one market on one trading date.

    Fetches the last ``WINDOW_BARS`` price bars per instrument, computes
    technical indicators over the full window, then extracts the as-of
    (latest) row for each instrument into the snapshot.

    Args:
        conn: Open psycopg3 async connection (read-only access required).
        market: MIC exchange code, e.g. ``"XNAS"``.
        trade_date: The trading date to snapshot.

    Returns:
        A fully populated :class:`Snapshot` ready for serialisation.

    Raises:
        ValueError: If no active instruments are found for ``market``.
    """
    # ── 1. Universe ───────────────────────────────────────────────────────────
    cur = await conn.execute(
        """
        SELECT i.id, i.symbol, i.sector, i.industry
          FROM theeyebeta.instruments i
          JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
         WHERE e.code = %s AND i.active
         ORDER BY i.symbol
        """,
        (market,),
    )
    universe_rows = await cur.fetchall()
    if not universe_rows:
        raise ValueError(f"No active instruments for market {market!r}")

    instrument_ids = [r[0] for r in universe_rows]
    universe = [
        UniverseEntry(
            instrument_id=r[0],
            symbol=r[1],
            sector=r[2],
            industry=r[3],
        )
        for r in universe_rows
    ]
    log.debug("universe_loaded", market=market, count=len(universe))

    # ── 2. Price window (last WINDOW_BARS bars per instrument ≤ trade_date) ──
    cur2 = await conn.execute(
        """
        WITH ranked AS (
            SELECT instrument_id, ts, open, high, low, close, adj_close, volume,
                   ROW_NUMBER() OVER (
                       PARTITION BY instrument_id ORDER BY ts DESC
                   ) AS rn
              FROM theeyebeta.prices_daily
             WHERE instrument_id = ANY(%s)
               AND ts <= (%s::date + interval '23:59:59')
        )
        SELECT instrument_id, ts, open, high, low, close, adj_close, volume
          FROM ranked
         WHERE rn <= %s
         ORDER BY instrument_id, ts
        """,
        (instrument_ids, trade_date, WINDOW_BARS),
    )
    bars_rows = await cur2.fetchall()
    log.debug("bars_fetched", market=market, rows=len(bars_rows))

    bars = pl.DataFrame(
        bars_rows,
        schema=["instrument_id", "ts", "open", "high", "low", "close", "adj_close", "volume"],
        orient="row",
    ).with_columns(
        [
            pl.col("instrument_id").cast(pl.Int64),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("adj_close").cast(pl.Float64),
            pl.col("volume").cast(pl.Int64),
        ]
    )

    # ── 3. Compute technicals over the full window ────────────────────────────
    enriched = add_technicals(bars)

    # ── 4. Extract last bar per instrument (the as-of row) ───────────────────
    latest = (
        enriched.sort(["instrument_id", "ts"])
        .group_by("instrument_id", maintain_order=True)
        .last()
    )

    # ── 5. Build prices + technicals dicts keyed by symbol ───────────────────
    id_to_symbol = {r[0]: r[1] for r in universe_rows}
    prices: dict[str, PriceBlock] = {}
    technicals: dict[str, TechnicalsBlock] = {}

    for row in latest.iter_rows(named=True):
        sym = id_to_symbol[row["instrument_id"]]
        prices[sym] = PriceBlock(
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            adj_close=row["adj_close"],
            volume=int(row["volume"]),
        )
        technicals[sym] = TechnicalsBlock(
            atr14=row["atr14"],
            rsi14=row["rsi14"],
            zscore20=row["zscore20"],
            bb_upper20_2=row["bb_upper20_2"],
            bb_lower20_2=row["bb_lower20_2"],
            sma20=row["sma20"],
            sma50=row["sma50"],
            sma200=row["sma200"],
        )

    # ── 6. Macro (latest value ≤ trade_date per series) ───────────────────────
    cur3 = await conn.execute(
        """
        SELECT DISTINCT ON (series_code) series_code, value
          FROM theeyebeta.macro_indicators
         WHERE ts <= (%s::date + interval '23:59:59')
         ORDER BY series_code, ts DESC
        """,
        (trade_date,),
    )
    macro_rows = await cur3.fetchall()
    macro = {r[0]: float(r[1]) for r in macro_rows}

    # ── 7. Assemble ───────────────────────────────────────────────────────────
    return Snapshot(
        market=market,
        snapshot_id=uuid4(),
        as_of=datetime.combine(
            trade_date,
            datetime.max.time(),
            tzinfo=timezone.utc,
        ),
        trade_date=str(trade_date),
        universe=universe,
        prices=prices,
        technicals=technicals,
        macro=macro,
    )
