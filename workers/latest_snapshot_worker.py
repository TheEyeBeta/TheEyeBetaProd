"""Materialize theeyebeta.latest_snapshots from canonical Prod ingest tables."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult

log = structlog.get_logger()

MATERIALIZE_SQL = """
INSERT INTO theeyebeta.latest_snapshots (
    instrument_id,
    ticker_id,
    last_price,
    last_price_ts,
    price_change_pct,
    price_change_abs,
    prev_close,
    high_52w,
    low_52w,
    volume,
    avg_volume_10d,
    avg_volume_30d,
    volume_ratio,
    sma_10,
    sma_50,
    sma_200,
    ema_10,
    ema_50,
    ema_200,
    rsi_14,
    macd,
    macd_signal,
    macd_hist,
    pe_ratio,
    forward_pe,
    price_to_book,
    price_to_sales,
    market_cap,
    price_vs_sma_50,
    price_vs_sma_200,
    price_vs_ema_50,
    price_vs_ema_200,
    is_bullish,
    is_oversold,
    is_overbought,
    latest_signal,
    signal_strategy,
    signal_confidence,
    signal_ts,
    updated_at
)
SELECT
    i.id AS instrument_id,
    m.public_ticker_id AS ticker_id,
    COALESCE(pi.close, pd.close) AS last_price,
    COALESCE(pi.ts, pd.ts) AS last_price_ts,
    CASE
        WHEN pd_prev.close IS NOT NULL AND pd_prev.close <> 0 THEN
            ((COALESCE(pi.close, pd.close) - pd_prev.close) / pd_prev.close) * 100
        ELSE NULL
    END AS price_change_pct,
    CASE
        WHEN pd_prev.close IS NOT NULL THEN COALESCE(pi.close, pd.close) - pd_prev.close
        ELSE NULL
    END AS price_change_abs,
    pd_prev.close AS prev_close,
    range52.high_52w,
    range52.low_52w,
    COALESCE(pi.volume, pd.volume) AS volume,
    vol.avg_volume_10d,
    vol.avg_volume_30d,
    CASE
        WHEN vol.avg_volume_10d IS NOT NULL AND vol.avg_volume_10d > 0
             AND COALESCE(pi.volume, pd.volume) IS NOT NULL
            THEN COALESCE(pi.volume, pd.volume)::numeric / vol.avg_volume_10d
        ELSE NULL
    END AS volume_ratio,
    ind.sma_10,
    ind.sma_50,
    ind.sma_200,
    ind.ema_10,
    ind.ema_50,
    ind.ema_200,
    ind.rsi_14,
    ind.macd,
    ind.macd_signal,
    ind.macd_hist,
    val.pe_ttm AS pe_ratio,
    val.forward_pe,
    val.pb AS price_to_book,
    val.ps_ttm AS price_to_sales,
    COALESCE(cap.market_cap, val.market_cap) AS market_cap,
    CASE
        WHEN ind.sma_50 IS NOT NULL AND ind.sma_50 <> 0 THEN
            ((COALESCE(pi.close, pd.close) - ind.sma_50) / ind.sma_50) * 100
        ELSE NULL
    END AS price_vs_sma_50,
    CASE
        WHEN ind.sma_200 IS NOT NULL AND ind.sma_200 <> 0 THEN
            ((COALESCE(pi.close, pd.close) - ind.sma_200) / ind.sma_200) * 100
        ELSE NULL
    END AS price_vs_sma_200,
    CASE
        WHEN ind.ema_50 IS NOT NULL AND ind.ema_50 <> 0 THEN
            ((COALESCE(pi.close, pd.close) - ind.ema_50) / ind.ema_50) * 100
        ELSE NULL
    END AS price_vs_ema_50,
    CASE
        WHEN ind.ema_200 IS NOT NULL AND ind.ema_200 <> 0 THEN
            ((COALESCE(pi.close, pd.close) - ind.ema_200) / ind.ema_200) * 100
        ELSE NULL
    END AS price_vs_ema_200,
    CASE
        WHEN ind.sma_50 IS NOT NULL AND ind.sma_200 IS NOT NULL THEN
            COALESCE(pi.close, pd.close) > ind.sma_50 AND ind.sma_50 > ind.sma_200
        ELSE NULL
    END AS is_bullish,
    CASE
        WHEN ind.rsi_14 IS NOT NULL THEN ind.rsi_14 < 30
        ELSE NULL
    END AS is_oversold,
    CASE
        WHEN ind.rsi_14 IS NOT NULL THEN ind.rsi_14 > 70
        ELSE NULL
    END AS is_overbought,
    sig.signal AS latest_signal,
    sig.strategy_name AS signal_strategy,
    sig.confidence AS signal_confidence,
    sig.ts AS signal_ts,
    now() AS updated_at
FROM theeyebeta.instruments i
JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
LEFT JOIN LATERAL (
    SELECT close, ts, volume
      FROM theeyebeta.prices_intraday
     WHERE instrument_id = i.id
     ORDER BY ts DESC
     LIMIT 1
) pi ON true
LEFT JOIN LATERAL (
    SELECT close, ts, volume
      FROM (
            SELECT p.ts::date AS d,
                   p.close,
                   p.ts,
                   p.volume,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.ts::date
                       ORDER BY
                           CASE p.source
                               WHEN 'massive' THEN 100
                               WHEN 'yfinance_backfill_prices' THEN 90
                               WHEN 'yfinance_gap_fix' THEN 90
                               WHEN 'yfinance' THEN 80
                               WHEN 'finnhub' THEN 70
                               WHEN 'public_mirror_backfill' THEN 60
                               WHEN 'public_mirror_active_universe' THEN 50
                               WHEN 'tick_rollup' THEN 40
                               WHEN 'csv' THEN 10
                               ELSE 0
                           END DESC,
                           p.ts DESC,
                           p.ingested_at DESC
                   ) AS rn
              FROM theeyebeta.prices_daily p
             WHERE p.instrument_id = i.id
      ) ranked
     WHERE rn = 1
     ORDER BY d DESC
     LIMIT 1
) pd ON true
LEFT JOIN LATERAL (
    SELECT close
      FROM (
            SELECT p.ts::date AS d,
                   p.close,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.ts::date
                       ORDER BY
                           CASE p.source
                               WHEN 'massive' THEN 100
                               WHEN 'yfinance_backfill_prices' THEN 90
                               WHEN 'yfinance_gap_fix' THEN 90
                               WHEN 'yfinance' THEN 80
                               WHEN 'finnhub' THEN 70
                               WHEN 'public_mirror_backfill' THEN 60
                               WHEN 'public_mirror_active_universe' THEN 50
                               WHEN 'tick_rollup' THEN 40
                               WHEN 'csv' THEN 10
                               ELSE 0
                           END DESC,
                           p.ts DESC,
                           p.ingested_at DESC
                   ) AS rn
              FROM theeyebeta.prices_daily p
             WHERE p.instrument_id = i.id
      ) ranked
     WHERE rn = 1
     ORDER BY d DESC
     OFFSET 1
     LIMIT 1
) pd_prev ON true
LEFT JOIN LATERAL (
    SELECT MAX(high) AS high_52w, MIN(low) AS low_52w
      FROM (
            SELECT p.ts::date AS d,
                   p.high,
                   p.low,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.ts::date
                       ORDER BY
                           CASE p.source
                               WHEN 'massive' THEN 100
                               WHEN 'yfinance_backfill_prices' THEN 90
                               WHEN 'yfinance_gap_fix' THEN 90
                               WHEN 'yfinance' THEN 80
                               WHEN 'finnhub' THEN 70
                               WHEN 'public_mirror_backfill' THEN 60
                               WHEN 'public_mirror_active_universe' THEN 50
                               WHEN 'tick_rollup' THEN 40
                               WHEN 'csv' THEN 10
                               ELSE 0
                           END DESC,
                           p.ts DESC,
                           p.ingested_at DESC
                   ) AS rn
              FROM theeyebeta.prices_daily p
             WHERE p.instrument_id = i.id
               AND p.ts >= now() - INTERVAL '365 days'
      ) ranked
     WHERE rn = 1
) range52 ON true
LEFT JOIN LATERAL (
    SELECT
        AVG(volume) FILTER (WHERE rn BETWEEN 1 AND 10) AS avg_volume_10d,
        AVG(volume) FILTER (WHERE rn BETWEEN 1 AND 30) AS avg_volume_30d
      FROM (
            SELECT volume,
                   ROW_NUMBER() OVER (ORDER BY d DESC) AS rn
              FROM (
                    SELECT p.ts::date AS d,
                           p.volume,
                           ROW_NUMBER() OVER (
                               PARTITION BY p.ts::date
                               ORDER BY
                                   CASE p.source
                                       WHEN 'massive' THEN 100
                                       WHEN 'yfinance_backfill_prices' THEN 90
                                       WHEN 'yfinance_gap_fix' THEN 90
                                       WHEN 'yfinance' THEN 80
                                       WHEN 'finnhub' THEN 70
                                       WHEN 'public_mirror_backfill' THEN 60
                                       WHEN 'public_mirror_active_universe' THEN 50
                                       WHEN 'tick_rollup' THEN 40
                                       WHEN 'csv' THEN 10
                                       ELSE 0
                                   END DESC,
                                   p.ts DESC,
                                   p.ingested_at DESC
                           ) AS daily_rn
                      FROM theeyebeta.prices_daily p
                     WHERE p.instrument_id = i.id
                       AND p.volume IS NOT NULL
              ) daily
             WHERE daily_rn = 1
        ) ranked
     WHERE rn <= 30
) vol ON true
LEFT JOIN LATERAL (
    SELECT sma_10, sma_50, sma_200, ema_10, ema_50, ema_200,
           rsi_14, macd, macd_signal, macd_hist
      FROM theeyebeta.ind_technical_daily
     WHERE instrument_id = i.id
     ORDER BY date DESC
     LIMIT 1
) ind ON true
LEFT JOIN LATERAL (
    SELECT pe_ttm, forward_pe, pb, ps_ttm, market_cap
      FROM theeyebeta.ind_valuation_daily
     WHERE instrument_id = i.id
     ORDER BY date DESC
     LIMIT 1
) val ON true
LEFT JOIN LATERAL (
    SELECT market_cap
      FROM theeyebeta.market_cap_daily
     WHERE instrument_id = i.id
     ORDER BY as_of_date DESC
     LIMIT 1
) cap ON true
LEFT JOIN LATERAL (
    SELECT signal, strategy_name, confidence, ts
      FROM theeyebeta.signals
     WHERE ticker_id = m.public_ticker_id
     ORDER BY ts DESC
     LIMIT 1
) sig ON true
WHERE i.active = true
  AND (pi.close IS NOT NULL OR pd.close IS NOT NULL)
ON CONFLICT (instrument_id) DO UPDATE SET
    ticker_id = EXCLUDED.ticker_id,
    last_price = EXCLUDED.last_price,
    last_price_ts = EXCLUDED.last_price_ts,
    price_change_pct = EXCLUDED.price_change_pct,
    price_change_abs = EXCLUDED.price_change_abs,
    prev_close = EXCLUDED.prev_close,
    high_52w = EXCLUDED.high_52w,
    low_52w = EXCLUDED.low_52w,
    volume = EXCLUDED.volume,
    avg_volume_10d = EXCLUDED.avg_volume_10d,
    avg_volume_30d = EXCLUDED.avg_volume_30d,
    volume_ratio = EXCLUDED.volume_ratio,
    sma_10 = EXCLUDED.sma_10,
    sma_50 = EXCLUDED.sma_50,
    sma_200 = EXCLUDED.sma_200,
    ema_10 = EXCLUDED.ema_10,
    ema_50 = EXCLUDED.ema_50,
    ema_200 = EXCLUDED.ema_200,
    rsi_14 = EXCLUDED.rsi_14,
    macd = EXCLUDED.macd,
    macd_signal = EXCLUDED.macd_signal,
    macd_hist = EXCLUDED.macd_hist,
    pe_ratio = EXCLUDED.pe_ratio,
    forward_pe = EXCLUDED.forward_pe,
    price_to_book = EXCLUDED.price_to_book,
    price_to_sales = EXCLUDED.price_to_sales,
    market_cap = EXCLUDED.market_cap,
    price_vs_sma_50 = EXCLUDED.price_vs_sma_50,
    price_vs_sma_200 = EXCLUDED.price_vs_sma_200,
    price_vs_ema_50 = EXCLUDED.price_vs_ema_50,
    price_vs_ema_200 = EXCLUDED.price_vs_ema_200,
    is_bullish = EXCLUDED.is_bullish,
    is_oversold = EXCLUDED.is_oversold,
    is_overbought = EXCLUDED.is_overbought,
    latest_signal = EXCLUDED.latest_signal,
    signal_strategy = EXCLUDED.signal_strategy,
    signal_confidence = EXCLUDED.signal_confidence,
    signal_ts = EXCLUDED.signal_ts,
    updated_at = EXCLUDED.updated_at
"""


async def count_active_universe(conn: asyncpg.Connection) -> int:
    """Return count of active instruments with a public ticker bridge."""
    value = await conn.fetchval(
        """
        SELECT COUNT(*)
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
         WHERE i.active
        """,
    )
    return int(value or 0)


async def materialize_latest_snapshots(conn: asyncpg.Connection) -> int:
    """Upsert latest_snapshots rows and return affected row count."""
    status = await conn.execute(MATERIALIZE_SQL)
    # asyncpg returns e.g. "INSERT 0 511"
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


class LatestSnapshotWorker(BaseWorker):
    """Build advisor-facing latest_snapshots from canonical theeyebeta tables."""

    worker_name = "LatestSnapshotWorker"
    worker_type = "latest_snapshot"
    display_name = "Latest Snapshot Materializer"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        active_universe = await count_active_universe(conn)
        rows_before = int(
            await conn.fetchval("SELECT COUNT(*) FROM theeyebeta.latest_snapshots") or 0,
        )

        if dry_run:
            priced = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT i.id)
                      FROM theeyebeta.instruments i
                      JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
                     WHERE i.active
                       AND (
                         EXISTS (
                           SELECT 1 FROM theeyebeta.prices_intraday pi
                            WHERE pi.instrument_id = i.id
                         )
                         OR EXISTS (
                           SELECT 1 FROM theeyebeta.prices_daily pd
                            WHERE pd.instrument_id = i.id
                         )
                       )
                    """,
                )
                or 0,
            )
            return WorkerResult(
                records_written=0,
                records_expected=priced,
                metadata={
                    "dry_run": True,
                    "trade_date": trade_date.isoformat(),
                    "active_universe": active_universe,
                    "priced_instruments": priced,
                    "rows_before": rows_before,
                },
            )

        written = await materialize_latest_snapshots(conn)
        rows_after = int(
            await conn.fetchval("SELECT COUNT(*) FROM theeyebeta.latest_snapshots") or 0,
        )
        max_updated = await conn.fetchval(
            "SELECT MAX(updated_at) FROM theeyebeta.latest_snapshots",
        )
        max_updated_at = max_updated.isoformat() if isinstance(max_updated, datetime) else None
        metadata = {
            "trade_date": trade_date.isoformat(),
            "active_universe": active_universe,
            "written": written,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "max_updated_at": max_updated_at,
            "materialized_at": datetime.now(UTC).isoformat(),
        }
        log.info("latest_snapshot_materialize_complete", **metadata)
        return WorkerResult(
            records_written=written,
            records_expected=active_universe,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = LatestSnapshotWorker()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Materialize theeyebeta.latest_snapshots for advisor/DataAPI consumers",
    )
    parser.add_argument("--date", help="Trade date YYYY-MM-DD (audit metadata only)")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
