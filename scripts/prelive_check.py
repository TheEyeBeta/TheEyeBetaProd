"""Pre-live go/no-go harness: 12 read-only checks against the live platform.

Usage:
    uv run python scripts/prelive_check.py            # table output
    uv run python scripts/prelive_check.py --json     # machine output

Exit code 0 only when zero checks FAIL (WARNs allowed). The DB session is
forced read-only server-side (SET default_transaction_read_only = on); this
script contains no INSERT/UPDATE/DELETE statements by design.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import shutil
import subprocess
import sys
import time as time_mod
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workers.base_worker import worker_database_url
from workers.gap_sentinel_worker import (
    check_canonical_freshness,
    check_pipeline_calendar_gaps,
    check_stuck_worker_runs,
    expected_latest_trading_day,
)
from workers.macro_features import build_macro_feature_block_from_row
from workers.sector_features import build_sector_context_from_rows

# Legacy public track ignored after Prod takeover.
PUBLIC_SEQUENCE: list[str] = []
PUBLIC_REQUIRED = ""
THEEYEBETA_SEQUENCE = [
    "0011_data_snapshots_packaged",
    "0012_sector_daily",
    "0013_prices_intraday",
    "0018_market_cap_universe",
    "0019_trading_calendar",
    "0020_worker_ops",
    "0021_pipeline_alerts",
    "0022_ind_technical_daily",
    "0023_sector_daily",
    "0024_public_ticker_map",
    "0025_signals_status_comment",
    "0026_admin_rbac",
    "0027_signals_schema_realign",
    "0028_totp_mfa",
    "0029_audit_worm_policy",
    "0030_audit_chain_status",
]
THEEYEBETA_REQUIRED = "0030_audit_chain_status"

WORKER_SET: list[str] = [
    "MacroIngestionWorker",
    "MacroRegimeWorker",
    "MassiveDailyIngestionWorker",
    "IntradayIngestionWorker",
    "IndicatorComputeWorker",
    "TheeyebetaIndicatorWorker",
    "daily_pipeline",
    "MarketCapFetchWorker",
    "MarketCapThresholdWorker",
    "GapSentinelWorker",
    "SectorAggregationWorker",
]
HEARTBEAT_MAX_AGE_HOURS = 26

SPOT_CHECK_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "XOM", "UNH"]
SPOT_PASS_REL = 0.001
SPOT_WARN_REL = 0.005

MASSIVE_ERA_START = date(2026, 6, 10)

BACKUP_DIR = Path("/home/the-eye-beta/backups")
MIN_BACKUP_BYTES = 5 * 1024**3  # 5 GiB sanity floor for ~118 GB DB
NO_BACKUP_MESSAGE = "\033[91mNO DATABASE BACKUP MECHANISM EXISTS — LAUNCH BLOCKER\033[0m"


@dataclass(slots=True)
class CheckResult:
    """Outcome of one pre-live check."""

    number: int
    name: str
    status: str  # PASS | FAIL | WARN
    evidence: str


def _seq_ok(head: str, required: str, sequence: list[str]) -> bool:
    if head not in sequence or required not in sequence:
        return False
    return sequence.index(head) >= sequence.index(required)


async def check_migration_heads(conn: asyncpg.Connection) -> CheckResult:
    beta = await conn.fetchval("SELECT version_num FROM theeyebeta.alembic_version")
    beta_ok = _seq_ok(str(beta), THEEYEBETA_REQUIRED, THEEYEBETA_SEQUENCE)
    evidence = f"theeyebeta={beta} (need >={THEEYEBETA_REQUIRED})"
    return CheckResult(1, "MIGRATION HEADS", "PASS" if beta_ok else "FAIL", evidence)


async def check_price_freshness(conn: asyncpg.Connection) -> CheckResult:
    result = await check_canonical_freshness(conn, dry_run=True)
    status = "PASS" if not result["violation"] else "FAIL"
    evidence = (
        f"latest={result['latest_theeyebeta_day']} rows={result['latest_theeyebeta_count']} "
        f"expected={result['expected_trading_day']} min_rows={result['min_rows_required']} "
        f"universe={result['active_universe']}"
    )
    return CheckResult(2, "CANONICAL PRICE FRESHNESS", status, evidence)


async def check_macro(conn: asyncpg.Connection) -> CheckResult:
    expected = await expected_latest_trading_day(conn)
    snap_date = await conn.fetchval(
        "SELECT MAX(as_of_date) FROM theeyebeta.macro_regime_snapshots",
    )
    problems: list[str] = []
    if snap_date is None or snap_date < expected:
        problems.append(f"snapshot stale ({snap_date} < {expected})")

    ranges = {
        "UNEMPLOYMENT_RATE": (3.0, 6.0),
        "IG_OAS": (50.0, 250.0),
        "BREAKEVEN_5Y": (1.5, 3.0),
        "BREAKEVEN_10Y": (1.5, 3.0),
    }
    for series, (lo, hi) in ranges.items():
        value = await conn.fetchval(
            """
            SELECT value FROM theeyebeta.macro_indicators
             WHERE series_code = $1 ORDER BY ts DESC LIMIT 1
            """,
            series,
        )
        if value is None:
            problems.append(f"{series} missing")
        elif not lo <= float(value) <= hi:
            problems.append(f"{series}={float(value)} outside [{lo},{hi}]")

    labels = await conn.fetchrow(
        """
        SELECT rate_environment, yield_curve, credit_environment,
               volatility_regime, dollar_regime
          FROM theeyebeta.macro_regime_snapshots
         ORDER BY as_of_date DESC LIMIT 1
        """,
    )
    known = sum(1 for v in (labels or {}).values() if v and v != "unknown") if labels else 0
    min_known_labels = 3
    if known < min_known_labels:
        problems.append(f"only {known}/5 regime labels known")

    status = "PASS" if not problems else "FAIL"
    evidence = f"snapshot={snap_date}, labels_known={known}/5" + (
        f"; problems: {'; '.join(problems)}" if problems else ""
    )
    return CheckResult(3, "MACRO FRESHNESS+SANITY", status, evidence)


async def check_open_critical_gaps(conn: asyncpg.Connection) -> CheckResult:
    count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM theeyebeta.audit_data_gaps
         WHERE remediation_state='OPEN' AND severity='CRITICAL'
        """,
    )
    return CheckResult(4, "GAPS", "PASS" if count == 0 else "FAIL", f"open CRITICAL gaps={count}")


async def check_calendar_sentinel(conn: asyncpg.Connection) -> CheckResult:
    pipeline = await check_pipeline_calendar_gaps(conn, dry_run=True)
    missing = list(pipeline["missing_pipeline_days"])
    untriaged: list[str] = []
    for day in missing:
        triaged = await conn.fetchval(
            """
            SELECT 1 FROM theeyebeta.audit_data_gaps
             WHERE trade_date = $1::date
               AND remediation_state IN ('RESOLVED','IGNORED')
               AND (remediation_notes ILIKE '%pipeline completion%'
                    OR remediation_notes ILIKE '%pipeline COMPLETED%')
             LIMIT 1
            """,
            date.fromisoformat(day),
        )
        if not triaged:
            untriaged.append(day)

    massive_missing: list[str] = []
    rows = await conn.fetch(
        """
        SELECT calendar_date FROM theeyebeta.trading_calendar
         WHERE is_trading_day AND calendar_date >= $1 AND calendar_date < CURRENT_DATE
         ORDER BY calendar_date
        """,
        MASSIVE_ERA_START,
    )
    for row in rows:
        completed = await conn.fetchval(
            """
            SELECT 1 FROM theeyebeta.worker_runs
             WHERE worker_name='MassiveDailyIngestionWorker'
               AND trade_date=$1 AND status='COMPLETED' LIMIT 1
            """,
            row["calendar_date"],
        )
        if not completed:
            massive_missing.append(row["calendar_date"].isoformat())

    if untriaged or massive_missing:
        status = "FAIL"
    elif missing:
        status = "WARN"
    else:
        status = "PASS"
    evidence = (
        f"pipeline missing={len(missing)} (untriaged={untriaged or 'none'}); "
        f"massive missing(>= {MASSIVE_ERA_START})={massive_missing or 'none'}"
    )
    if missing and not untriaged:
        evidence += "; all missing days carry triaged (RESOLVED/IGNORED) gap notes"
    return CheckResult(5, "CALENDAR SENTINEL", status, evidence)


async def check_stuck(conn: asyncpg.Connection) -> CheckResult:
    stuck = await check_stuck_worker_runs(conn, dry_run=True)
    status = "PASS" if not stuck else "FAIL"
    names = [f"{s['worker_name']}#{s['run_id']}" for s in stuck]
    return CheckResult(6, "STUCK RUNS", status, f"stuck STARTED>2h: {names or 'none'}")


async def check_circuit_breakers(conn: asyncpg.Connection) -> CheckResult:
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM theeyebeta.trask_circuit_breakers WHERE state='open'",
    )
    return CheckResult(7, "CIRCUIT BREAKERS", "PASS" if count == 0 else "FAIL", f"open={count}")


async def check_canonical_spot(conn: asyncpg.Connection) -> CheckResult:
    """Verify canonical daily closes exist for spot symbols (no public bridge)."""
    expected = await expected_latest_trading_day(conn)
    missing: list[str] = []
    for symbol in SPOT_CHECK_SYMBOLS:
        close = await conn.fetchval(
            """
            SELECT p.close
              FROM theeyebeta.instruments i
              JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id
              JOIN theeyebeta.prices_daily p ON p.instrument_id = i.id
             WHERE i.symbol = $1 AND i.active AND p.ts::date = $2
             LIMIT 1
            """,
            symbol,
            expected,
        )
        if close is None:
            missing.append(symbol)
    if missing:
        return CheckResult(
            8,
            "CANONICAL SPOT CHECK",
            "FAIL",
            f"missing {expected} closes for {missing}",
        )
    return CheckResult(
        8,
        "CANONICAL SPOT CHECK",
        "PASS",
        f"{len(SPOT_CHECK_SYMBOLS)} symbols have {expected} canonical closes",
    )


async def check_argos_dry_run(conn: asyncpg.Connection) -> CheckResult:
    try:
        expected = await expected_latest_trading_day(conn)
        macro_row = await conn.fetchrow(
            """
            SELECT * FROM theeyebeta.macro_regime_snapshots
             WHERE as_of_date = $1 LIMIT 1
            """,
            expected,
        )
        macro = build_macro_feature_block_from_row(macro_row)
        sector_rows = await conn.fetch(
            """
            SELECT sector, rotation_rank, rel_strength_spx_30d,
                   pct_above_sma_50, pct_above_sma_200
              FROM theeyebeta.sector_daily WHERE as_of_date = $1
            """,
            expected,
        )
        sector = build_sector_context_from_rows(
            [dict(r) for r in sector_rows],
            expected if sector_rows else None,
        )
        gaps = sorted({*macro.get("data_gaps", []), *sector.get("data_gaps", [])})
    except Exception as exc:  # noqa: BLE001 - any exception is the FAIL condition
        return CheckResult(9, "ARGOS DRY-RUN", "FAIL", f"exception: {type(exc).__name__}: {exc}")
    status = "PASS" if not gaps else "WARN"
    return CheckResult(9, "ARGOS DRY-RUN", status, f"data_gaps={gaps}")


async def check_heartbeats(conn: asyncpg.Connection) -> CheckResult:
    stale: list[str] = []
    for worker in WORKER_SET:
        last = await conn.fetchval(
            "SELECT last_heartbeat FROM theeyebeta.worker_heartbeats WHERE worker_id = $1",
            worker,
        )
        if last is None or datetime.now(UTC) - last > timedelta(hours=HEARTBEAT_MAX_AGE_HOURS):
            stale.append(f"{worker}={last.isoformat() if last else 'never'}")
    status = "PASS" if not stale else "FAIL"
    return CheckResult(
        10,
        "HEARTBEATS",
        status,
        f"{len(WORKER_SET) - len(stale)}/{len(WORKER_SET)} fresh (<{HEARTBEAT_MAX_AGE_HOURS}h)"
        + (f"; stale: {stale}" if stale else ""),
    )


async def check_disk(conn: asyncpg.Connection) -> CheckResult:
    data_dir = await conn.fetchval("SHOW data_directory")
    min_free_pct = 20.0
    try:
        usage = shutil.disk_usage(data_dir)
        free_pct = usage.free / usage.total * 100
    except OSError as exc:
        return CheckResult(11, "DISK", "FAIL", f"cannot stat {data_dir}: {exc}")
    status = "PASS" if free_pct >= min_free_pct else "FAIL"
    return CheckResult(
        11,
        "DISK",
        status,
        f"{free_pct:.1f}% free on {data_dir} (need >={min_free_pct:.0f}%)",
    )


def _newest_backup_dump() -> tuple[Path, float, int] | None:
    """Return newest *.dump under BACKUP_DIR as (path, mtime, size_bytes)."""
    if not BACKUP_DIR.is_dir():
        return None
    dumps = sorted(
        BACKUP_DIR.glob("*.dump"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not dumps:
        return None
    newest = dumps[0]
    stat = newest.stat()
    return newest, stat.st_mtime, stat.st_size


def _discover_backup_automation() -> list[str]:
    hits: list[str] = []
    for cron_dir in ("/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly", "/etc/cron.weekly"):
        for entry in glob.glob(f"{cron_dir}/*"):
            try:
                text = Path(entry).read_text(errors="ignore")
            except OSError:
                continue
            if any(tool in text for tool in ("pg_dump", "pg_basebackup", "wal-g", "pgbackrest")):
                hits.append(entry)
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, discovery only
            ["/usr/bin/systemctl", "list-timers", "--all", "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
        hits.extend(
            line.split()[-2]
            for line in out.splitlines()
            if any(k in line.lower() for k in ("backup", "pg_dump", "wal-g", "pgbackrest"))
            and "dpkg-db-backup" not in line
        )
    except OSError:
        pass
    return hits


async def check_backup_recency(_conn: asyncpg.Connection) -> CheckResult:
    automation = _discover_backup_automation()
    now = time_mod.time()
    newest = _newest_backup_dump()
    if newest is None:
        return CheckResult(
            12,
            "BACKUP RECENCY",
            "FAIL",
            f"no *.dump in {BACKUP_DIR}; automation={automation or 'none found'}. "
            f"{NO_BACKUP_MESSAGE}",
        )

    path, mtime, size_bytes = newest
    age_h = (now - mtime) / 3600
    size_gib = size_bytes / (1024**3)
    fresh = age_h < 24
    size_ok = size_bytes >= MIN_BACKUP_BYTES
    evidence = (
        f"newest {path} age={age_h:.1f}h size={size_gib:.1f}GiB "
        f"(need <24h and >={MIN_BACKUP_BYTES // (1024**3)}GiB); "
        f"automation={automation or 'none found'}"
    )
    if fresh and size_ok:
        return CheckResult(12, "BACKUP RECENCY", "PASS", evidence)
    if not fresh:
        evidence += f". {NO_BACKUP_MESSAGE}"
    elif not size_ok:
        evidence += "; dump too small — likely incomplete or wrong artifact"
    return CheckResult(12, "BACKUP RECENCY", "FAIL", evidence)


CHECKS = [
    check_migration_heads,
    check_price_freshness,
    check_macro,
    check_open_critical_gaps,
    check_calendar_sentinel,
    check_stuck,
    check_circuit_breakers,
    check_canonical_spot,
    check_argos_dry_run,
    check_heartbeats,
    check_disk,
    check_backup_recency,
]


def render_table(results: list[CheckResult]) -> str:
    name_w = max(len(r.name) for r in results)
    lines = [
        f"{'#':>2}  {'CHECK':<{name_w}}  {'STATUS':<6}  EVIDENCE",
        f"{'-' * 2}  {'-' * name_w}  {'-' * 6}  {'-' * 60}",
    ]
    lines.extend(f"{r.number:>2}  {r.name:<{name_w}}  {r.status:<6}  {r.evidence}" for r in results)
    fails = sum(1 for r in results if r.status == "FAIL")
    warns = sum(1 for r in results if r.status == "WARN")
    lines.append("")
    lines.append(f"RESULT: {len(results)} checks, {fails} FAIL, {warns} WARN")
    return "\n".join(lines)


async def run_checks() -> list[CheckResult]:
    """Run all 12 checks over a server-side read-only session."""
    conn = await asyncpg.connect(worker_database_url())
    try:
        await conn.execute("SET default_transaction_read_only = on")
        results = []
        for check in CHECKS:
            try:
                results.append(await check(conn))
            except Exception as exc:  # noqa: BLE001 - a crashed check is a FAIL
                index = CHECKS.index(check) + 1
                results.append(
                    CheckResult(index, check.__name__, "FAIL", f"check crashed: {exc}"),
                )
        return results
    finally:
        await conn.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Pre-live go/no-go checks (read-only)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    results = asyncio.run(run_checks())
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "number": r.number,
                        "name": r.name,
                        "status": r.status,
                        "evidence": r.evidence,
                    }
                    for r in results
                ],
                indent=2,
            ),
        )
    else:
        print(render_table(results))
    sys.exit(0 if all(r.status != "FAIL" for r in results) else 1)


if __name__ == "__main__":
    main()
