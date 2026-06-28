#!/usr/bin/env python3
"""Audit canonical daily price quality issues.

The script is read-only. It reports duplicate daily bars and bounded split-scale
segments so the API/read path can normalize them without mutating historical
price rows.

CLI:
    uv run python scripts/audit_price_quality.py
    uv run python scripts/audit_price_quality.py --symbols NVDA,GOOGL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import asyncpg

PROD_ROOT = Path(__file__).resolve().parents[1]
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import worker_database_url  # noqa: E402

REPAIR_SOURCE = "price_repair_scale"

SOURCE_PRIORITY_SQL = """
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
END
"""

SUMMARY_SQL = """
WITH per_day AS (
    SELECT p.instrument_id,
           p.ts::date AS d,
           COUNT(*) AS rows_on_date,
           MIN(p.close) FILTER (WHERE p.close > 0) AS min_close,
           MAX(p.close) FILTER (WHERE p.close > 0) AS max_close
      FROM theeyebeta.prices_daily p
      JOIN theeyebeta.instruments i ON i.id = p.instrument_id AND i.active
     WHERE p.ts::date BETWEEN $1 AND $2
     GROUP BY p.instrument_id, p.ts::date
    HAVING COUNT(*) > 1
       AND MIN(p.close) FILTER (WHERE p.close > 0) IS NOT NULL
)
SELECT COUNT(DISTINCT instrument_id)::bigint AS symbols_with_duplicates,
       COUNT(*)::bigint AS duplicate_dates,
       COALESCE(SUM(rows_on_date - 1), 0)::bigint AS extra_rows,
       MAX(max_close / NULLIF(min_close, 0))::float AS max_same_day_ratio,
       COUNT(*) FILTER (WHERE max_close / NULLIF(min_close, 0) >= $3)::bigint
           AS duplicate_dates_over_threshold
  FROM per_day
"""

TOP_DUPLICATES_SQL = """
WITH per_day AS (
    SELECT p.instrument_id,
           p.ts::date AS d,
           COUNT(*) AS rows_on_date,
           MIN(p.close) FILTER (WHERE p.close > 0) AS min_close,
           MAX(p.close) FILTER (WHERE p.close > 0) AS max_close,
           STRING_AGG(DISTINCT p.source, ', ' ORDER BY p.source) AS sources
      FROM theeyebeta.prices_daily p
      JOIN theeyebeta.instruments i ON i.id = p.instrument_id AND i.active
     WHERE p.ts::date BETWEEN $1 AND $2
     GROUP BY p.instrument_id, p.ts::date
    HAVING COUNT(*) > 1
       AND MIN(p.close) FILTER (WHERE p.close > 0) IS NOT NULL
)
SELECT i.symbol,
       d,
       rows_on_date,
       min_close::float AS min_close,
       max_close::float AS max_close,
       (max_close / NULLIF(min_close, 0))::float AS ratio,
       sources
  FROM per_day pd
  JOIN theeyebeta.instruments i ON i.id = pd.instrument_id
 WHERE max_close / NULLIF(min_close, 0) >= $3
 ORDER BY ratio DESC, i.symbol, d
 LIMIT $4
"""

CANDIDATES_SQL = f"""
WITH candidate_instruments AS (
    SELECT DISTINCT p.instrument_id
      FROM theeyebeta.prices_daily p
      JOIN theeyebeta.instruments i ON i.id = p.instrument_id AND i.active
     WHERE p.ts::date BETWEEN $1 AND $2
       AND ($6::text[] IS NULL OR UPPER(i.symbol) = ANY($6::text[]))
     GROUP BY p.instrument_id, p.ts::date
    HAVING COUNT(*) > 1
       AND MIN(p.close) FILTER (WHERE p.close > 0) IS NOT NULL
       AND EXISTS (
            SELECT 1
              FROM UNNEST($3::float8[]) AS f(factor)
             WHERE ABS((MAX(p.close) FILTER (WHERE p.close > 0)
                    / NULLIF(MIN(p.close) FILTER (WHERE p.close > 0), 0))
                    / f.factor - 1.0) <= $4
       )
    UNION
    SELECT i.id
      FROM theeyebeta.instruments i
     WHERE $6::text[] IS NOT NULL
       AND UPPER(i.symbol) = ANY($6::text[])
),
ranked_prices AS (
    SELECT i.symbol,
           p.instrument_id,
           p.ts::date AS d,
           p.close,
           p.source,
           ROW_NUMBER() OVER (
               PARTITION BY p.instrument_id, p.ts::date
               ORDER BY {SOURCE_PRIORITY_SQL} DESC, p.ts DESC, p.ingested_at DESC
           ) AS rn
      FROM theeyebeta.prices_daily p
      JOIN candidate_instruments ci ON ci.instrument_id = p.instrument_id
      JOIN theeyebeta.instruments i ON i.id = p.instrument_id
     WHERE p.ts::date BETWEEN $1 AND $2
       AND p.close > 0
       AND p.source <> $8
),
series AS (
    SELECT *,
           LAG(d) OVER w AS prev_d,
           LAG(close) OVER w AS prev_close
      FROM ranked_prices
     WHERE rn = 1
    WINDOW w AS (PARTITION BY instrument_id ORDER BY d)
),
jumps AS (
    SELECT *,
           close / NULLIF(prev_close, 0) AS ratio,
           CASE
               WHEN close / NULLIF(prev_close, 0) < 1.0 / 3.0 THEN 'down'
               WHEN close / NULLIF(prev_close, 0) > 3.0 THEN 'up'
           END AS direction
      FROM series
     WHERE prev_close IS NOT NULL
),
intervals AS (
    SELECT d.symbol,
           d.instrument_id,
           d.d AS start_date,
           u.prev_d AS end_date,
           u.d AS up_date,
           d.ratio AS down_ratio,
           u.ratio AS up_ratio,
           ((1.0 / d.ratio) + u.ratio) / 2.0 AS estimated_factor,
           ROW_NUMBER() OVER (PARTITION BY d.instrument_id, d.d ORDER BY u.d) AS pick
      FROM jumps d
      JOIN jumps u
        ON u.instrument_id = d.instrument_id
       AND u.direction = 'up'
       AND u.d > d.d
       AND u.d <= d.d + ($5::int * INTERVAL '1 day')
       AND ABS(LN(u.ratio) - LN(1.0 / d.ratio)) <= LN(1.0 + $4)
     WHERE d.direction = 'down'
),
matched AS (
    SELECT intervals.*,
           nearest.factor
      FROM intervals
      JOIN LATERAL (
            SELECT f.factor
              FROM UNNEST($3::float8[]) AS f(factor)
             ORDER BY ABS(intervals.estimated_factor / f.factor - 1.0)
             LIMIT 1
      ) nearest ON ABS(intervals.estimated_factor / nearest.factor - 1.0) <= $4
     WHERE intervals.pick = 1
)
SELECT symbol,
       instrument_id,
       start_date,
       end_date,
       up_date,
       factor::int AS factor,
       down_ratio::float AS down_ratio,
       up_ratio::float AS up_ratio,
       estimated_factor::float AS estimated_factor,
       (
           SELECT COUNT(*)
             FROM ranked_prices r
            WHERE r.instrument_id = matched.instrument_id
              AND r.rn = 1
              AND r.d BETWEEN matched.start_date AND matched.end_date
       )::bigint AS rows_to_repair,
       (
           SELECT COUNT(*)
             FROM theeyebeta.prices_daily rep
            WHERE rep.instrument_id = matched.instrument_id
              AND rep.source = $8
              AND rep.ts::date BETWEEN matched.start_date AND matched.end_date
       )::bigint AS existing_repairs,
       (
           SELECT STRING_AGG(DISTINCT r.source, ', ' ORDER BY r.source)
             FROM ranked_prices r
            WHERE r.instrument_id = matched.instrument_id
              AND r.rn = 1
              AND r.d BETWEEN matched.start_date AND matched.end_date
       ) AS sources
  FROM matched
 ORDER BY symbol, start_date
 LIMIT $7
"""

def _parse_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip().upper() for part in raw.split(",") if part.strip()]


def _parse_factors(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _row_dict(row: asyncpg.Record) -> dict[str, object]:
    return dict(row.items())


async def _audit(args: argparse.Namespace) -> dict[str, object]:
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    symbols = _parse_symbols(args.symbols)
    factors = _parse_factors(args.factors)
    conn = await asyncpg.connect(worker_database_url())
    try:
        summary = await conn.fetchrow(SUMMARY_SQL, start, end, args.duplicate_threshold)
        top_duplicates = await conn.fetch(
            TOP_DUPLICATES_SQL,
            start,
            end,
            args.duplicate_threshold,
            args.limit,
        )
        candidates = await conn.fetch(
            CANDIDATES_SQL,
            start,
            end,
            factors,
            args.tolerance,
            args.max_interval_days,
            symbols,
            args.limit,
            REPAIR_SOURCE,
        )

        repair_candidates = [_row_dict(row) for row in candidates]
        open_repair_candidates = [
            row
            for row in repair_candidates
            if int(row["existing_repairs"] or 0) < int(row["rows_to_repair"] or 0)
        ]
        return {
            "dry_run": not args.apply,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "factors": factors,
            "duplicate_summary": _row_dict(summary) if summary else {},
            "top_duplicate_mismatches": [_row_dict(row) for row in top_duplicates],
            "repair_candidates": repair_candidates,
            "open_repair_candidates": open_repair_candidates,
            "repair_source": REPAIR_SOURCE,
            "inserted_repairs": 0,
            "apply_results": [],
        }
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit canonical daily price quality")
    parser.add_argument("--start", default=date(2021, 1, 1).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--symbols", help="Comma-separated symbols for deep repair detection")
    parser.add_argument("--factors", default="10,20", help="Comma-separated repair factors")
    parser.add_argument("--tolerance", type=float, default=0.20)
    parser.add_argument("--duplicate-threshold", type=float, default=2.0)
    parser.add_argument("--max-interval-days", type=int, default=370)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--apply", action="store_true", help="Disabled; audit is read-only")
    args = parser.parse_args()
    if args.apply:
        msg = "--apply is disabled; this audit is read-only after repair overlay regression."
        raise SystemExit(msg)
    payload = asyncio.run(_audit(args))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
