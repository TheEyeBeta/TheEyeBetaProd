"""Snapshot builder: Postgres reads + zinc_native.ta batch technicals."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg
import numpy as np
import structlog
from uuid6 import uuid7

from snapshot_packager.macro_keys import macro_key_for_series
from snapshot_packager.markets import MARKET_EXCHANGE_CASE_SQL, VALID_MARKETS
from snapshot_packager.technicals_native import snapshot_technicals_last
from zinc_schemas.packaged_snapshot import (
    PACKAGED_SCHEMA_VERSION,
    PackagedNewsItem,
    PackagedPriceBar,
    PackagedSnapshotV1,
    PackagedTechnicals,
    PackagedUniverseEntry,
)

log = structlog.get_logger()

WINDOW_BARS = 250

_UNIVERSE_SQL = f"""
SELECT i.id, i.symbol, i.sector, i.industry
  FROM theeyebeta.instruments i
  JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
 WHERE i.active
   AND {MARKET_EXCHANGE_CASE_SQL} = $1
 ORDER BY i.symbol
"""  # noqa: S608


def _finite_or_none(value: float) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return float(value)


class SnapshotBuilder:
    """Build agent-ready packaged snapshots for one market and trade date."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def build(self, market: str, trade_date: date) -> dict[str, Any]:
        """Assemble a v1 packaged snapshot dict.

        Args:
            market: Aggregated market code (US, HK, JP, TW, CN).
            trade_date: Trading calendar date.

        Returns:
            JSON-serialisable dict matching :class:`PackagedSnapshotV1`.

        Raises:
            ValueError: If ``market`` is unknown or the universe is empty.
        """
        market_upper = market.upper()
        if market_upper not in VALID_MARKETS:
            msg = f"Unknown market {market!r}"
            raise ValueError(msg)

        as_of = datetime.combine(trade_date, time(23, 59, 59), tzinfo=UTC)
        day_end = as_of
        news_start = as_of - timedelta(hours=24)

        async with self._pool.acquire() as conn:
            universe_rows = await conn.fetch(_UNIVERSE_SQL, market_upper)
            if not universe_rows:
                msg = f"No active instruments for market {market_upper!r}"
                raise ValueError(msg)

            instrument_ids = [int(row["id"]) for row in universe_rows]
            bars_rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT instrument_id, ts, open, high, low, close, adj_close, volume,
                           ROW_NUMBER() OVER (
                               PARTITION BY instrument_id ORDER BY ts DESC
                           ) AS rn
                      FROM theeyebeta.prices_daily
                     WHERE instrument_id = ANY($1::bigint[])
                       AND ts <= $2
                )
                SELECT instrument_id, ts, open, high, low, close, adj_close, volume
                  FROM ranked
                 WHERE rn <= $3
                 ORDER BY instrument_id, ts
                """,
                instrument_ids,
                day_end,
                WINDOW_BARS,
            )

            macro_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (series_code) series_code, value
                  FROM theeyebeta.macro_indicators
                 WHERE ts <= $1
                 ORDER BY series_code, ts DESC
                """,
                day_end,
            )

            news_rows = await conn.fetch(
                """
                SELECT id, headline, tickers, published_at
                  FROM theeyebeta.news_articles
                 WHERE published_at >= $1
                   AND published_at <= $2
                 ORDER BY published_at DESC
                 LIMIT 50
                """,
                news_start,
                day_end,
            )

        universe = [
            PackagedUniverseEntry(
                symbol=row["symbol"],
                instrument_id=int(row["id"]),
                sector=row["sector"],
                industry=row["industry"],
            )
            for row in universe_rows
        ]
        id_to_symbol = {int(row["id"]): row["symbol"] for row in universe_rows}

        bars_by_id: dict[int, list[tuple]] = {inst_id: [] for inst_id in instrument_ids}
        for row in bars_rows:
            bars_by_id[int(row["instrument_id"])].append(row)

        ohlc_series: list[np.ndarray] = []
        ordered_ids: list[int] = []
        for inst_id in instrument_ids:
            rows = bars_by_id.get(inst_id, [])
            if not rows:
                ohlc_series.append(np.empty((0, 4), dtype=np.float64))
                ordered_ids.append(inst_id)
                continue
            ohlc = np.empty((len(rows), 4), dtype=np.float64)
            for index, bar in enumerate(rows):
                close = float(bar["adj_close"] if bar["adj_close"] is not None else bar["close"])
                ohlc[index, 0] = float(bar["open"])
                ohlc[index, 1] = float(bar["high"])
                ohlc[index, 2] = float(bar["low"])
                ohlc[index, 3] = close
            ohlc_series.append(ohlc)
            ordered_ids.append(inst_id)

        technicals_last = snapshot_technicals_last(ohlc_series)

        prices: dict[str, PackagedPriceBar] = {}
        technicals: dict[str, PackagedTechnicals] = {}
        for inst_id, tech in zip(ordered_ids, technicals_last, strict=True):
            symbol = id_to_symbol[inst_id]
            rows = bars_by_id.get(inst_id, [])
            if not rows:
                continue
            last = rows[-1]
            prices[symbol] = PackagedPriceBar(
                open=float(last["open"]),
                high=float(last["high"]),
                low=float(last["low"]),
                close=float(last["close"]),
                adj_close=float(last["adj_close"]) if last["adj_close"] is not None else None,
                volume=int(last["volume"]),
            )
            technicals[symbol] = PackagedTechnicals(
                atr14=_finite_or_none(tech.atr14),
                adx14=_finite_or_none(tech.adx14),
                rsi14=_finite_or_none(tech.rsi14),
                zscore20=_finite_or_none(tech.zscore20),
                bb_upper20_2=_finite_or_none(tech.bb_upper20_2),
                bb_lower20_2=_finite_or_none(tech.bb_lower20_2),
            )

        macro = {
            macro_key_for_series(row["series_code"]): float(row["value"]) for row in macro_rows
        }
        news_summary = [
            PackagedNewsItem(
                id=row["id"],
                headline=row["headline"],
                tickers=list(row["tickers"] or []),
                published_at=row["published_at"],
            )
            for row in news_rows
        ]

        snapshot = PackagedSnapshotV1(
            schema_version=PACKAGED_SCHEMA_VERSION,
            market=market_upper,
            snapshot_id=uuid7(),
            as_of=as_of,
            universe=universe,
            prices=prices,
            technicals=technicals,
            macro=macro,
            news_summary=news_summary,
        )
        log.info(
            "snapshot_built",
            market=market_upper,
            trade_date=str(trade_date),
            universe=len(universe),
            news=len(news_summary),
        )
        return snapshot.model_dump(mode="json")
