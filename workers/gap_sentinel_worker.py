"""Calendar gap sentinel — detects missing pipeline completions and stuck worker runs."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta

import asyncpg

from scripts.audit_price_quality import CANDIDATES_SQL, REPAIR_SOURCE, SUMMARY_SQL
from workers.base_worker import BaseWorker, WorkerResult

PIPELINE_WORKER_NAME = "daily_pipeline"
LOOKBACK_TRADING_DAYS = 10
STUCK_STARTED_HOURS = 2
CANONICAL_COVERAGE_THRESHOLD = 0.95
CANONICAL_POST_CLOSE_UTC = time(22, 0)
PRICE_QUALITY_START = date(2021, 1, 1)
PRICE_QUALITY_DUPLICATE_THRESHOLD = 2.0
PRICE_QUALITY_FACTORS = [10.0, 20.0]
PRICE_QUALITY_TOLERANCE = 0.20
PRICE_QUALITY_MAX_INTERVAL_DAYS = 370
PRICE_QUALITY_CANDIDATE_LIMIT = 25


def _metadata_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _record_dict(row: asyncpg.Record | dict[str, object] | None) -> dict[str, object]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return {key: _metadata_value(value) for key, value in row.items()}
    return {key: _metadata_value(value) for key, value in row.items()}


async def check_pipeline_calendar_gaps(
    conn: asyncpg.Connection,
    *,
    as_of: date | None = None,
    lookback_trading_days: int = LOOKBACK_TRADING_DAYS,
    dry_run: bool = False,
) -> dict[str, object]:
    """Return missing pipeline days and newly created gap/alert identifiers.

    With ``dry_run=True`` missing days are reported but no gap or alert rows
    are written.
    """
    today = as_of or date.today()
    trading_days = await conn.fetch(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT $2
        """,
        today,
        lookback_trading_days,
    )
    missing_days: list[date] = []
    gap_ids: list[int] = []
    alert_ids: list[int] = []

    for row in trading_days:
        trade_day: date = row["calendar_date"]
        completed = await conn.fetchval(
            """
            SELECT 1
              FROM theeyebeta.worker_runs
             WHERE worker_name = $1
               AND trade_date = $2
               AND status = 'COMPLETED'
             LIMIT 1
            """,
            PIPELINE_WORKER_NAME,
            trade_day,
        )
        if completed:
            continue

        missing_days.append(trade_day)
        if dry_run:
            continue

        # Any prior gap for the day counts — including RESOLVED/IGNORED ones:
        # a historical day that was triaged stays triaged and must not be
        # re-flagged every morning.
        existing_gap = await conn.fetchval(
            """
            SELECT gap_id
              FROM theeyebeta.audit_data_gaps
             WHERE trade_date = $1
               AND (remediation_notes ILIKE '%pipeline completion%'
                    OR remediation_notes ILIKE '%pipeline COMPLETED%')
             LIMIT 1
            """,
            trade_day,
        )
        if existing_gap:
            continue

        note = (
            f"Trading day {trade_day.isoformat()} has no daily_pipeline COMPLETED "
            f"audit_worker_runs row."
        )
        day_start = datetime.combine(trade_day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        gap_id = await conn.fetchval(
            """
            INSERT INTO theeyebeta.audit_data_gaps
                (dataset_type, trade_date, expected_start, expected_end,
                 expected_count, actual_count, gap_start, gap_end,
                 severity, remediation_state, remediation_notes, metadata)
            VALUES (
                'price_daily',
                $1::date,
                $2::timestamptz,
                $3::timestamptz,
                1,
                0,
                $2::timestamptz,
                $3::timestamptz,
                'CRITICAL',
                'OPEN',
                $4,
                $5::jsonb
            )
            RETURNING gap_id
            """,
            trade_day,
            day_start,
            day_end,
            note,
            json.dumps({"worker_name": PIPELINE_WORKER_NAME, "trade_date": trade_day.isoformat()}),
        )
        gap_ids.append(int(gap_id))
        alert_id = await conn.fetchval(
            """
            INSERT INTO theeyebeta.audit_alerts
                (alert_type, severity, trade_date, worker_name, gap_id, title, message, metadata)
            VALUES (
                'DATA_GAP',
                'CRITICAL',
                $1,
                $2,
                $3,
                $4,
                $5,
                $6::jsonb
            )
            RETURNING alert_id
            """,
            trade_day,
            "GapSentinelWorker",
            gap_id,
            f"Trading day with no pipeline completion: {trade_day.isoformat()}",
            note,
            json.dumps({"worker_name": PIPELINE_WORKER_NAME}),
        )
        alert_ids.append(int(alert_id))

    stuck = await check_stuck_worker_runs(conn, dry_run=dry_run)
    return {
        "as_of": today.isoformat(),
        "missing_pipeline_days": [d.isoformat() for d in missing_days],
        "gaps_created": gap_ids,
        "alerts_created": alert_ids,
        "stuck_runs": stuck,
    }


async def expected_latest_trading_day(
    conn: asyncpg.Connection,
    *,
    as_of: datetime | None = None,
) -> date:
    """Return the most recent trading day that should have canonical prices.

    Excludes the current UTC calendar day before 22:00 UTC (pre-close window).
    """
    now = as_of or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    cutoff = now.date()
    if now.time() >= CANONICAL_POST_CLOSE_UTC:
        cutoff = now.date() + timedelta(days=1)

    value = await conn.fetchval(
        """
        SELECT calendar_date
          FROM theeyebeta.trading_calendar
         WHERE is_trading_day
           AND calendar_date < $1
         ORDER BY calendar_date DESC
         LIMIT 1
        """,
        cutoff,
    )
    if value is None:
        msg = f"No trading day found before {cutoff.isoformat()}"
        raise RuntimeError(msg)
    return value


async def check_canonical_freshness(
    conn: asyncpg.Connection,
    *,
    as_of: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Verify theeyebeta.prices_daily matches the expected latest trading day.

    Creates a CRITICAL audit_data_gaps row and alert when the canonical schema is
    stale or under-covered relative to the active instrument universe.
    """
    expected_day = await expected_latest_trading_day(conn, as_of=as_of)
    # Denominator is the fetchable universe: active AND mapped to a public ticker.
    # Unmapped international names are excluded from ingestion and must not
    # count against coverage.
    active = int(
        await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM theeyebeta.instruments i
              JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
             WHERE i.active
            """,
        )
        or 0,
    )
    min_rows = int(active * CANONICAL_COVERAGE_THRESHOLD)

    latest_day = await conn.fetchval("SELECT MAX(ts::date) FROM theeyebeta.prices_daily")
    latest_count = 0
    if latest_day is not None:
        latest_count = int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM theeyebeta.prices_daily WHERE ts::date = $1",
                latest_day,
            )
            or 0,
        )

    stale_day = latest_day is None or latest_day < expected_day
    under_covered = latest_count < min_rows
    violation = stale_day or under_covered

    gap_ids: list[int] = []
    alert_ids: list[int] = []
    if violation and not dry_run:
        stale_label = latest_day.isoformat() if latest_day is not None else "none"
        note = (
            f"Canonical schema stale: theeyebeta.prices_daily latest={stale_label} "
            f"({latest_count} rows); expected>={expected_day.isoformat()} "
            f"with >={min_rows} rows (schema=theeyebeta)."
        )
        existing_gap = await conn.fetchval(
            """
            SELECT gap_id
              FROM theeyebeta.audit_data_gaps
             WHERE trade_date = $1
               AND remediation_state = 'OPEN'
               AND remediation_notes ILIKE '%Canonical schema stale%'
             LIMIT 1
            """,
            expected_day,
        )
        if existing_gap is None:
            day_start = datetime.combine(expected_day, datetime.min.time(), tzinfo=UTC)
            day_end = day_start + timedelta(days=1)
            gap_id = await conn.fetchval(
                """
                INSERT INTO theeyebeta.audit_data_gaps
                    (dataset_type, trade_date, expected_start, expected_end,
                     expected_count, actual_count, gap_start, gap_end,
                     severity, remediation_state, remediation_notes, metadata)
                VALUES (
                    'price_daily',
                    $1::date,
                    $2::timestamptz,
                    $3::timestamptz,
                    $4,
                    $5,
                    $2::timestamptz,
                    $3::timestamptz,
                    'CRITICAL',
                    'OPEN',
                    $6,
                    $7::jsonb
                )
                RETURNING gap_id
                """,
                expected_day,
                day_start,
                day_end,
                min_rows,
                latest_count,
                note,
                json.dumps(
                    {
                        "schema": "theeyebeta",
                        "expected_day": expected_day.isoformat(),
                        "latest_day": stale_label,
                        "latest_count": latest_count,
                    },
                ),
            )
            gap_ids.append(int(gap_id))
            alert_id = await conn.fetchval(
                """
                INSERT INTO theeyebeta.audit_alerts (
                    alert_type, severity, trade_date, worker_name,
                    gap_id, title, message, metadata
                )
                VALUES (
                    'DATA_GAP',
                    'CRITICAL',
                    $1,
                    'GapSentinelWorker',
                    $2,
                    $3,
                    $4,
                    $5::jsonb
                )
                RETURNING alert_id
                """,
                expected_day,
                gap_id,
                f"Canonical schema stale: theeyebeta prices at {stale_label}",
                note,
                json.dumps({"check": "canonical_freshness", "schema": "theeyebeta"}),
            )
            alert_ids.append(int(alert_id))

    return {
        "expected_trading_day": expected_day.isoformat(),
        "latest_theeyebeta_day": latest_day.isoformat() if latest_day else None,
        "latest_theeyebeta_count": latest_count,
        "active_universe": active,
        "min_rows_required": min_rows,
        "violation": violation,
        "gaps_created": gap_ids,
        "alerts_created": alert_ids,
    }


async def check_price_quality_anomalies(
    conn: asyncpg.Connection,
    *,
    start: date = PRICE_QUALITY_START,
    end: date | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Flag duplicate-date price conflicts and bounded split-scale intervals."""
    audit_end = end or date.today()
    summary_row = await conn.fetchrow(
        SUMMARY_SQL,
        start,
        audit_end,
        PRICE_QUALITY_DUPLICATE_THRESHOLD,
    )
    candidates = await conn.fetch(
        CANDIDATES_SQL,
        start,
        audit_end,
        PRICE_QUALITY_FACTORS,
        PRICE_QUALITY_TOLERANCE,
        PRICE_QUALITY_MAX_INTERVAL_DAYS,
        None,
        PRICE_QUALITY_CANDIDATE_LIMIT,
        REPAIR_SOURCE,
    )
    summary = _record_dict(summary_row)
    candidate_rows = [_record_dict(row) for row in candidates]
    duplicate_conflicts = int(summary.get("duplicate_dates_over_threshold") or 0)
    violation = duplicate_conflicts > 0 or bool(candidate_rows)
    alert_ids: list[int] = []

    if violation and not dry_run:
        existing = await conn.fetchval(
            """
            SELECT alert_id
              FROM theeyebeta.audit_alerts
             WHERE alert_type = 'DATA_QUALITY'
               AND worker_name = 'GapSentinelWorker'
               AND title = 'Daily price quality anomalies detected'
               AND acknowledged_at IS NULL
               AND resolved_at IS NULL
             LIMIT 1
            """,
        )
        if existing is None:
            candidate_symbols = sorted({str(row["symbol"]) for row in candidate_rows})
            message = (
                f"Daily price audit found {duplicate_conflicts} duplicate-date conflicts "
                f"over {PRICE_QUALITY_DUPLICATE_THRESHOLD:g}x"
            )
            if candidate_symbols:
                message += f"; bounded scale candidates: {', '.join(candidate_symbols)}"
            alert_id = await conn.fetchval(
                """
                INSERT INTO theeyebeta.audit_alerts (
                    alert_type, severity, trade_date, worker_name,
                    title, message, metadata
                )
                VALUES (
                    'DATA_QUALITY',
                    'CRITICAL',
                    $1,
                    'GapSentinelWorker',
                    'Daily price quality anomalies detected',
                    $2,
                    $3::jsonb
                )
                RETURNING alert_id
                """,
                audit_end,
                message,
                json.dumps(
                    {
                        "check": "price_quality_anomalies",
                        "start": start.isoformat(),
                        "end": audit_end.isoformat(),
                        "duplicate_summary": summary,
                        "repair_candidates": candidate_rows,
                    },
                    default=str,
                ),
            )
            alert_ids.append(int(alert_id))

    return {
        "start": start.isoformat(),
        "end": audit_end.isoformat(),
        "duplicate_summary": summary,
        "repair_candidates": candidate_rows,
        "violation": violation,
        "alerts_created": alert_ids,
    }


async def remediate_open_gaps(
    conn: asyncpg.Connection,
    *,
    as_of: date | None = None,
) -> dict[str, object]:
    """Close OPEN CRITICAL gaps whose underlying conditions are now satisfied."""
    today = as_of or date.today()
    resolved_pipeline: list[str] = []
    resolved_canonical: list[str] = []

    pipeline_gaps = await conn.fetch(
        """
        SELECT gap_id, trade_date
          FROM theeyebeta.audit_data_gaps
         WHERE remediation_state = 'OPEN'
           AND severity = 'CRITICAL'
           AND remediation_notes ILIKE '%daily_pipeline COMPLETED%'
        """,
    )
    for row in pipeline_gaps:
        trade_day: date = row["trade_date"]
        completed = await conn.fetchval(
            """
            SELECT 1
              FROM theeyebeta.worker_runs
             WHERE worker_name = $1
               AND trade_date = $2
               AND status = 'COMPLETED'
             LIMIT 1
            """,
            PIPELINE_WORKER_NAME,
            trade_day,
        )
        if not completed:
            continue
        await conn.execute(
            """
            UPDATE theeyebeta.audit_data_gaps
               SET remediation_state = 'RESOLVED',
                   remediation_notes = COALESCE(remediation_notes, '')
                       || ' | Auto-resolved: daily_pipeline COMPLETED',
                   updated_at = now()
             WHERE gap_id = $1
            """,
            row["gap_id"],
        )
        resolved_pipeline.append(trade_day.isoformat())

    canonical = await check_canonical_freshness(conn, as_of=freshness_as_of(today), dry_run=True)
    if not canonical["violation"]:
        canonical_gaps = await conn.fetch(
            """
            SELECT gap_id, trade_date
              FROM theeyebeta.audit_data_gaps
             WHERE remediation_state = 'OPEN'
               AND severity = 'CRITICAL'
               AND remediation_notes ILIKE '%Canonical schema stale%'
            """,
        )
        for row in canonical_gaps:
            await conn.execute(
                """
                UPDATE theeyebeta.audit_data_gaps
                   SET remediation_state = 'RESOLVED',
                       remediation_notes = COALESCE(remediation_notes, '')
                           || ' | Auto-resolved: canonical freshness OK',
                       updated_at = now()
                 WHERE gap_id = $1
                """,
                row["gap_id"],
            )
            resolved_canonical.append(row["trade_date"].isoformat())

    return {
        "resolved_pipeline_days": resolved_pipeline,
        "resolved_canonical_days": resolved_canonical,
    }


def freshness_as_of(trade_date: date, *, now: datetime | None = None) -> datetime:
    """Return the as-of timestamp used for the canonical freshness check.

    For the current (or a future) trade date the real wall clock must be used,
    otherwise a morning run would treat the day as fully elapsed and demand
    prices that cannot exist before the 22:00 UTC post-close cutoff.
    Historical dates keep end-of-day semantics so back-dated audits still
    evaluate the full day.

    Args:
        trade_date: The trade date the worker was invoked for.
        now: Injectable current time for tests; defaults to ``datetime.now(UTC)``.

    Returns:
        The as-of timestamp to pass to :func:`check_canonical_freshness`.
    """
    current = now or datetime.now(UTC)
    if trade_date >= current.date():
        return current
    return datetime.combine(trade_date, datetime.max.time(), tzinfo=UTC)


async def check_stuck_worker_runs(
    conn: asyncpg.Connection,
    *,
    dry_run: bool = False,
) -> list[dict[str, object]]:
    """Flag STARTED rows older than two hours with no terminal follow-up.

    With ``dry_run=True`` stuck runs are reported but no alert rows are written.
    """
    rows = await conn.fetch(
        """
        SELECT run_id, worker_name, trade_date, started_at
          FROM theeyebeta.worker_runs r
         WHERE status = 'STARTED'
           AND started_at < now() - ($1::text || ' hours')::interval
           AND NOT EXISTS (
               SELECT 1
                 FROM theeyebeta.worker_runs t
                WHERE t.worker_name = r.worker_name
                  AND t.trade_date = r.trade_date
                  AND t.status IN ('COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED')
                  AND t.run_id > r.run_id
           )
        """,
        str(STUCK_STARTED_HOURS),
    )
    created: list[dict[str, object]] = []
    for row in rows:
        message = (
            f"{row['worker_name']} run_id={row['run_id']} stuck in STARTED since "
            f"{row['started_at'].isoformat()}"
        )
        if dry_run:
            created.append(
                {
                    "alert_id": None,
                    "worker_name": row["worker_name"],
                    "run_id": row["run_id"],
                },
            )
            continue
        exists = await conn.fetchval(
            """
            SELECT 1
              FROM theeyebeta.audit_alerts
             WHERE alert_type = 'DAY_INCOMPLETE'
               AND worker_name = $1
               AND trade_date = $2
               AND message = $3
               AND created_at > now() - interval '1 day'
             LIMIT 1
            """,
            row["worker_name"],
            row["trade_date"],
            message,
        )
        if exists:
            continue
        alert_id = await conn.fetchval(
            """
            INSERT INTO theeyebeta.audit_alerts
                (alert_type, severity, trade_date, worker_name, title, message, metadata)
            VALUES (
                'DAY_INCOMPLETE',
                'WARN',
                $1,
                $2,
                'worker crashed mid-run',
                $3,
                $4::jsonb
            )
            RETURNING alert_id
            """,
            row["trade_date"],
            row["worker_name"],
            message,
            json.dumps({"run_id": row["run_id"]}),
        )
        created.append(
            {
                "alert_id": int(alert_id),
                "worker_name": row["worker_name"],
                "run_id": row["run_id"],
            },
        )
    return created


class GapSentinelWorker(BaseWorker):
    """Audit worker wrapper around calendar gap checks."""

    worker_name = "GapSentinelWorker"
    worker_type = "audit"
    display_name = "Gap Sentinel Worker"

    async def execute(
        self,
        conn: asyncpg.Connection,
        trade_date: date,
        *,
        dry_run: bool,
    ) -> WorkerResult:
        as_of_dt = freshness_as_of(trade_date)
        if dry_run:
            pipeline = await check_pipeline_calendar_gaps(conn, as_of=trade_date, dry_run=True)
            canonical = await check_canonical_freshness(conn, as_of=as_of_dt, dry_run=True)
            price_quality = await check_price_quality_anomalies(conn, end=trade_date, dry_run=True)
            return WorkerResult(
                records_written=0,
                records_expected=0,
                metadata={
                    "dry_run": True,
                    **pipeline,
                    "canonical_freshness": canonical,
                    "price_quality": price_quality,
                },
            )

        pipeline = await check_pipeline_calendar_gaps(conn, as_of=trade_date)
        canonical = await check_canonical_freshness(conn, as_of=as_of_dt)
        price_quality = await check_price_quality_anomalies(conn, end=trade_date)
        resolved = await remediate_open_gaps(conn, as_of=trade_date)
        gaps_created = len(pipeline["gaps_created"]) + len(canonical["gaps_created"])
        alerts_created = (
            len(pipeline["alerts_created"])
            + len(canonical["alerts_created"])
            + len(pipeline["stuck_runs"])
            + len(price_quality["alerts_created"])
        )
        return WorkerResult(
            records_written=gaps_created + alerts_created,
            records_expected=0,
            metadata={
                **pipeline,
                "canonical_freshness": canonical,
                "price_quality": price_quality,
                "remediation": resolved,
            },
        )


def _parse_date(raw: str | None) -> date:
    return date.fromisoformat(raw) if raw else date.today()


async def _async_main(args: argparse.Namespace) -> None:
    target_date = _parse_date(args.date)
    worker = GapSentinelWorker()
    result = await worker.run(
        target_date,
        run_type=args.run_type,
        dry_run=args.dry_run,
    )
    print(json.dumps({"worker": worker.worker_name, **result.metadata}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the gap sentinel worker")
    parser.add_argument("--date", help="As-of date YYYY-MM-DD; default today")
    parser.add_argument(
        "--run-type",
        default="scheduled",
        choices=["manual", "scheduled", "recovery"],
    )
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(_async_main(parser.parse_args()))


if __name__ == "__main__":
    main()
