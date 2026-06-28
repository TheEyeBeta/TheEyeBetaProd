#!/usr/bin/env python3
"""Mirror public indicator/metric tables into theeyebeta and backfill sector_daily.

Replicates mapped-universe metrics from public.* to theeyebeta.* via
public_ticker_map, then runs sector aggregation for every trading day that has
indicators but no sector row yet.

CLI:
    uv run python scripts/mirror_public_metrics_to_theeyebeta.py --dry-run
    uv run python scripts/mirror_public_metrics_to_theeyebeta.py --apply
    uv run python scripts/mirror_public_metrics_to_theeyebeta.py --apply --steps sector
    uv run python scripts/mirror_public_metrics_to_theeyebeta.py --apply --start 2022-01-03
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
if str(PROD_ROOT) not in sys.path:
    sys.path.insert(0, str(PROD_ROOT))

from workers.base_worker import worker_database_url  # noqa: E402
from workers.sector_aggregation_worker import SectorAggregationWorker  # noqa: E402

log = structlog.get_logger()

DEFAULT_START = date(2022, 1, 3)
DEFAULT_BATCH_DAYS = 30
CHECKPOINT_PATH = PROD_ROOT / "reports" / "metrics_backfill_checkpoint.json"

MIRROR_TABLES = (
    ("public.ind_technical_daily", "theeyebeta.ind_technical_daily"),
    ("public.ind_risk_daily", "theeyebeta.ind_risk_daily"),
    ("public.returns_snapshot_daily", "theeyebeta.returns_snapshot_daily"),
    ("public.ind_valuation_daily", "theeyebeta.ind_valuation_daily"),
)


async def _table_columns(conn: asyncpg.Connection, table_name: str) -> list[str]:
    schema, table = table_name.split(".", 1)
    rows = await conn.fetch(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = $1
           AND table_name = $2
         ORDER BY ordinal_position
        """,
        schema,
        table,
    )
    return [str(row["column_name"]) for row in rows]


async def _sync_table_for_dates(
    conn: asyncpg.Connection,
    source: str,
    target: str,
    dates: list[date],
    *,
    dry_run: bool,
) -> int:
    if not dates:
        return 0

    source_cols = await _table_columns(conn, source)
    target_cols = await _table_columns(conn, target)
    common = [col for col in source_cols if col in target_cols and col not in {"instrument_id"}]
    if "ticker_id" not in common or "date" not in common:
        msg = f"Cannot sync {source} -> {target}: missing ticker_id/date"
        raise RuntimeError(msg)

    if dry_run:
        return 0

    insert_cols = [*common, "instrument_id"]
    select_exprs = [f"s.{col}" for col in common] + ["m.instrument_id"]
    update_cols = [col for col in insert_cols if col not in {"instrument_id", "date"}]
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
    order_terms = ["m.instrument_id", "s.date"]
    if "computed_at" in common:
        order_terms.append("s.computed_at DESC NULLS LAST")

    sql = f"""
        INSERT INTO {target} ({", ".join(insert_cols)})
        SELECT DISTINCT ON (m.instrument_id, s.date)
            {", ".join(select_exprs)}
          FROM {source} s
          JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = s.ticker_id
         WHERE s.date = ANY($1::date[])
         ORDER BY {", ".join(order_terms)}
        ON CONFLICT (instrument_id, date) DO UPDATE SET
            {updates}
    """  # noqa: S608
    result = await conn.execute(sql, dates)
    return int(result.split()[-1]) if result else 0


async def _mirror_dates(
    conn: asyncpg.Connection,
    *,
    start: date,
    end: date,
) -> list[date]:
    """Trading days with public indicator coverage in range (partition-scoped)."""
    dates: list[date] = []
    for year in range(start.year, end.year + 1):
        table = f"public.ind_technical_daily_y{year}"
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM information_schema.tables
                 WHERE table_schema = 'public'
                   AND table_name = $1
            )
            """,
            f"ind_technical_daily_y{year}",
        )
        if not exists:
            continue
        year_start = max(start, date(year, 1, 1))
        year_end = min(end, date(year, 12, 31))
        rows = await conn.fetch(
            f"""
            SELECT DISTINCT date
              FROM {table}
             WHERE date BETWEEN $1 AND $2
             ORDER BY date
            """,  # noqa: S608
            year_start,
            year_end,
        )
        dates.extend(row["date"] for row in rows)
    return dates


async def _trading_days(
    conn: asyncpg.Connection,
    *,
    start: date,
    end: date,
) -> list[date]:
    rows = await conn.fetch(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date BETWEEN $1 AND $2
         ORDER BY calendar_date
        """,
        start,
        end,
    )
    calendar_days = [row["calendar_date"] for row in rows]
    if calendar_days and calendar_days[0] <= start:
        return calendar_days
    return await _mirror_dates(conn, start=start, end=end)


async def _latest_trading_day(conn: asyncpg.Connection) -> date:
    return await conn.fetchval(
        """
        SELECT MAX(calendar_date)
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date <= CURRENT_DATE
        """,
    )


def _chunk_dates(dates: list[date], batch_size: int) -> list[list[date]]:
    return [dates[i : i + batch_size] for i in range(0, len(dates), batch_size)]


def _load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_checkpoint(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))


async def mirror_metrics(
    conn: asyncpg.Connection,
    *,
    dates: list[date],
    batch_days: int,
    dry_run: bool,
    checkpoint_path: Path,
    resume: bool,
) -> dict[str, int]:
    checkpoint = _load_checkpoint(checkpoint_path) if resume else {}
    last_mirror_date = checkpoint.get("last_mirror_date")
    if last_mirror_date:
        resume_from = date.fromisoformat(last_mirror_date)
        dates = [d for d in dates if d > resume_from]
        log.info("mirror_resume", after=last_mirror_date, remaining_days=len(dates))

    totals: dict[str, int] = {target: 0 for _, target in MIRROR_TABLES}
    for batch in _chunk_dates(dates, batch_days):
        batch_counts: dict[str, int] = {}
        for source, target in MIRROR_TABLES:
            written = await _sync_table_for_dates(conn, source, target, batch, dry_run=dry_run)
            batch_counts[target] = written
            totals[target] += written
        log.info(
            "mirror_batch",
            start=batch[0].isoformat(),
            end=batch[-1].isoformat(),
            dry_run=dry_run,
            counts=batch_counts,
        )
        if not dry_run:
            checkpoint["last_mirror_date"] = batch[-1].isoformat()
            _save_checkpoint(checkpoint_path, checkpoint)
    return totals


async def _sector_dates_needing_backfill(
    conn: asyncpg.Connection,
    *,
    start: date,
    end: date,
    skip_existing: bool,
) -> list[date]:
    if skip_existing:
        rows = await conn.fetch(
            """
            SELECT DISTINCT i.date
              FROM theeyebeta.ind_technical_daily i
             WHERE i.date BETWEEN $1 AND $2
               AND NOT EXISTS (
                     SELECT 1
                       FROM theeyebeta.sector_daily s
                      WHERE s.as_of_date = i.date
                   )
             ORDER BY i.date
            """,
            start,
            end,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT DISTINCT date
              FROM theeyebeta.ind_technical_daily
             WHERE date BETWEEN $1 AND $2
             ORDER BY date
            """,
            start,
            end,
        )
    return [row["date"] for row in rows]


async def backfill_sector(
    *,
    dates: list[date],
    dry_run: bool,
    checkpoint_path: Path,
    resume: bool,
) -> dict[str, int]:
    checkpoint = _load_checkpoint(checkpoint_path) if resume else {}
    last_sector_date = checkpoint.get("last_sector_date")
    if last_sector_date:
        resume_from = date.fromisoformat(last_sector_date)
        dates = [d for d in dates if d > resume_from]
        log.info("sector_resume", after=last_sector_date, remaining_days=len(dates))

    worker = SectorAggregationWorker()
    written_total = 0
    failed = 0
    for trade_date in dates:
        try:
            result = await worker.run(trade_date, run_type="recovery", dry_run=dry_run)
            written_total += int(result.records_written or 0)
            log.info(
                "sector_day",
                trade_date=trade_date.isoformat(),
                records_written=result.records_written,
                dry_run=dry_run,
            )
            if not dry_run:
                checkpoint["last_sector_date"] = trade_date.isoformat()
                _save_checkpoint(checkpoint_path, checkpoint)
        except Exception:
            failed += 1
            log.exception("sector_day_failed", trade_date=trade_date.isoformat())
    return {"sector_rows_written": written_total, "sector_days_failed": failed}


async def run_backfill(
    *,
    start: date,
    end: date,
    steps: set[str],
    batch_days: int,
    dry_run: bool,
    skip_existing_sector: bool,
    checkpoint_path: Path,
    resume: bool,
) -> dict:
    conn = await asyncpg.connect(worker_database_url())
    try:
        if end is None:
            end = await _latest_trading_day(conn)
        trading_days = await _trading_days(conn, start=start, end=end)
        log.info(
            "backfill_plan",
            start=start.isoformat(),
            end=end.isoformat(),
            trading_days=len(trading_days),
            steps=sorted(steps),
            dry_run=dry_run,
        )

        summary: dict = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "trading_days": len(trading_days),
            "dry_run": dry_run,
        }

        if "mirror" in steps:
            summary["mirror_counts"] = await mirror_metrics(
                conn,
                dates=trading_days,
                batch_days=batch_days,
                dry_run=dry_run,
                checkpoint_path=checkpoint_path,
                resume=resume,
            )
    finally:
        await conn.close()

    if "sector" in steps:
        conn = await asyncpg.connect(worker_database_url())
        try:
            sector_dates = await _sector_dates_needing_backfill(
                conn,
                start=start,
                end=end,
                skip_existing=skip_existing_sector,
            )
        finally:
            await conn.close()
        log.info("sector_dates", count=len(sector_dates))
        summary["sector"] = await backfill_sector(
            dates=sector_dates,
            dry_run=dry_run,
            checkpoint_path=checkpoint_path,
            resume=resume,
        )

    return summary


def _parse_date(raw: str | None) -> date | None:
    return date.fromisoformat(raw) if raw else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mirror public metrics to theeyebeta and backfill sector_daily",
    )
    parser.add_argument("--start", default=DEFAULT_START.isoformat(), help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument(
        "--steps",
        default="all",
        help="Comma-separated: mirror, sector, all (default: all)",
    )
    parser.add_argument("--batch-days", type=int, default=DEFAULT_BATCH_DAYS)
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no writes")
    parser.add_argument("--apply", action="store_true", help="Perform writes (default is dry-run)")
    parser.add_argument(
        "--skip-existing-sector",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip sector dates that already have rows (default: true)",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint file")
    parser.add_argument("--checkpoint", default=str(CHECKPOINT_PATH))
    args = parser.parse_args()

    dry_run = not args.apply
    raw_steps = {s.strip().lower() for s in args.steps.split(",")}
    steps = {"mirror", "sector"} if "all" in raw_steps else raw_steps

    summary = asyncio.run(
        run_backfill(
            start=_parse_date(args.start) or DEFAULT_START,
            end=_parse_date(args.end),
            steps=steps,
            batch_days=args.batch_days,
            dry_run=dry_run,
            skip_existing_sector=args.skip_existing_sector,
            checkpoint_path=Path(args.checkpoint),
            resume=args.resume,
        ),
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
