"""Native technical indicator compute into theeyebeta.ind_technical_daily."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

import asyncpg
import structlog

from workers.base_worker import BaseWorker, WorkerResult
from workers.calendar import is_trading_day
from workers.indicator_math import (
    COMPUTE_VERSION,
    compute_indicators,
    indicator_row_to_bind,
)

log = structlog.get_logger()

HISTORY_CALENDAR_DAYS = 550
INSERT_BATCH = 500
UPSERT_SQL = """
    INSERT INTO theeyebeta.ind_technical_daily (
        instrument_id, date, ticker_id,
        sma_10, sma_50, sma_200,
        ema_10, ema_50, ema_200,
        rsi_14, macd, macd_signal, macd_hist,
        roc_10, roc_20,
        golden_cross_sma, death_cross_sma,
        as_of_date, computed_at, price_field, compute_version,
        ema_12, ema_26, momentum_rank_12_1
    )
    VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
        $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24
    )
    ON CONFLICT (instrument_id, date) DO UPDATE SET
        ticker_id = EXCLUDED.ticker_id,
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
        roc_10 = EXCLUDED.roc_10,
        roc_20 = EXCLUDED.roc_20,
        golden_cross_sma = EXCLUDED.golden_cross_sma,
        death_cross_sma = EXCLUDED.death_cross_sma,
        as_of_date = EXCLUDED.as_of_date,
        computed_at = EXCLUDED.computed_at,
        price_field = EXCLUDED.price_field,
        compute_version = EXCLUDED.compute_version,
        ema_12 = EXCLUDED.ema_12,
        ema_26 = EXCLUDED.ema_26,
        momentum_rank_12_1 = EXCLUDED.momentum_rank_12_1
"""


async def load_active_instruments(conn: asyncpg.Connection) -> list[tuple[int, int]]:
    """Return (instrument_id, public_ticker_id) for active mapped instruments."""
    rows = await conn.fetch(
        """
        SELECT i.id AS instrument_id, m.public_ticker_id AS ticker_id
          FROM theeyebeta.instruments i
          JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
         WHERE i.active
         ORDER BY i.id
        """,
    )
    return [(int(r["instrument_id"]), int(r["ticker_id"])) for r in rows]


async def load_price_history(
    conn: asyncpg.Connection,
    instrument_id: int,
    *,
    target_date: date,
) -> list[tuple[date, float, float, float, int]]:
    """Load daily OHLCV history for one instrument."""
    start = target_date - timedelta(days=HISTORY_CALENDAR_DAYS)
    rows = await conn.fetch(
        """
        WITH ranked_prices AS (
            SELECT ts::date AS d, close, high, low, volume,
                   ROW_NUMBER() OVER (
                       PARTITION BY ts::date
                       ORDER BY
                           CASE source
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
                           ts DESC,
                           ingested_at DESC
                   ) AS rn
              FROM theeyebeta.prices_daily
             WHERE instrument_id = $1
               AND ts::date BETWEEN $2 AND $3
        )
        SELECT d, close::float, high::float, low::float, volume::bigint
          FROM ranked_prices
         WHERE rn = 1
         ORDER BY d
        """,
        instrument_id,
        start,
        target_date,
    )
    return [
        (r["d"], float(r["close"]), float(r["high"]), float(r["low"]), int(r["volume"]))
        for r in rows
    ]


class IndicatorComputeWorker(BaseWorker):
    """Compute daily technical indicators from canonical prices."""

    worker_name = "IndicatorComputeWorker"
    worker_type = "indicators"
    display_name = "Indicator Compute"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        if not await is_trading_day(conn, trade_date):
            return WorkerResult(
                records_written=0,
                metadata={"skipped": True, "reason": "non_trading_day"},
            )

        instruments = await load_active_instruments(conn)
        priced_today = int(
            await conn.fetchval(
                """
                SELECT COUNT(DISTINCT instrument_id)
                  FROM theeyebeta.prices_daily
                 WHERE ts::date = $1
                """,
                trade_date,
            )
            or 0,
        )
        rows_before = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM theeyebeta.ind_technical_daily WHERE date = $1",
                trade_date,
            )
            or 0,
        )

        computed = 0
        skipped_no_bar = 0
        skipped_history = 0
        bind_rows: list[tuple[object, ...]] = []

        for instrument_id, ticker_id in instruments:
            history = await load_price_history(conn, instrument_id, target_date=trade_date)
            if not history or history[-1][0] != trade_date:
                skipped_no_bar += 1
                continue
            row = compute_indicators(
                history,
                instrument_id=instrument_id,
                ticker_id=ticker_id,
                target_date=trade_date,
            )
            if row is None:
                skipped_history += 1
                continue
            bind_rows.append(indicator_row_to_bind(row))
            computed += 1

        if dry_run:
            return WorkerResult(
                records_written=0,
                records_expected=priced_today,
                metadata={
                    "dry_run": True,
                    "trade_date": trade_date.isoformat(),
                    "active_universe": len(instruments),
                    "priced_today": priced_today,
                    "planned": computed,
                    "skipped_no_bar": skipped_no_bar,
                    "skipped_history": skipped_history,
                    "compute_version": COMPUTE_VERSION,
                },
            )

        written = 0
        for offset in range(0, len(bind_rows), INSERT_BATCH):
            batch = bind_rows[offset : offset + INSERT_BATCH]
            await conn.executemany(UPSERT_SQL, batch)
            written += len(batch)

        if written == 0 and priced_today > 0:
            msg = (
                f"Indicator compute produced no rows for {trade_date.isoformat()} "
                f"(priced_today={priced_today})"
            )
            raise RuntimeError(msg)

        rows_after = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM theeyebeta.ind_technical_daily WHERE date = $1",
                trade_date,
            )
            or 0,
        )
        metadata = {
            "trade_date": trade_date.isoformat(),
            "active_universe": len(instruments),
            "priced_today": priced_today,
            "computed": computed,
            "written": written,
            "skipped_no_bar": skipped_no_bar,
            "skipped_history": skipped_history,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "compute_version": COMPUTE_VERSION,
        }
        log.info("indicator_compute_complete", **metadata)
        return WorkerResult(
            records_written=written,
            records_expected=priced_today,
            metadata=metadata,
        )


async def _async_main(args: argparse.Namespace) -> None:
    target = date.fromisoformat(args.date) if args.date else date.today()
    worker = IndicatorComputeWorker()
    result = await worker.run(
        target,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2))


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Compute canonical daily indicators")
    parser.add_argument("--date", help="Trade date YYYY-MM-DD")
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
