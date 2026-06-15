"""
02_fred_macro_backfill.py
=========================
Fetches all missing FRED series into theeyebeta.macro_indicators.

Behaviour:
  - Checks what's already in the DB FIRST (never overwrites clean data)
  - For series already present: skips entirely (use --refresh flag to force update)
  - Latest-revision fetch only (single vintage)
  - Rate-limits to 90 req/min (safe below FRED's 120/min hard limit)
  - Retries on 429/5xx with exponential backoff
  - Idempotent UPSERT: ON CONFLICT DO NOTHING (safe to run multiple times)
  - Standalone script — does NOT modify any running worker

NOTE — vintage / ALFRED mode is DISABLED. The target table's unique key is
(series_code, ts) with no vintage_date column, so multi-vintage pulls would
silently collapse to one row per date. Until a vintage_date column is added,
every series (including REVISION_CRITICAL ones) is fetched latest-revision only.

Usage:
  pip install fredapi psycopg[binary] pandas tenacity

  export FRED_API_KEY="your_32_char_key_here"
  export DB_URL="postgresql://user:pass@host:5432/TheEyeBeta2025Live"

  # Backfill everything missing (recommended first run):
  python 02_fred_macro_backfill.py

  # Force refresh a specific series (re-fetches even if already in DB):
  python 02_fred_macro_backfill.py --series GDPC1 PAYEMS --refresh

  # Dry run — show what would be fetched without writing to DB:
  python 02_fred_macro_backfill.py --dry-run

  # Start date override (default: 2010-01-01 — gives 15y of history):
  python 02_fred_macro_backfill.py --start 2000-01-01
"""

import argparse
import logging
import os
import sys
import time

import pandas as pd
import psycopg
from fredapi import Fred

# ---------------------------------------------------------------------------
# IMPORT REGISTRY
# ---------------------------------------------------------------------------
from macro_series_registry import FRED_SERIES, REVISION_CRITICAL, SERIES_BY_CODE
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# DB_URL falls back to ADMIN_DATABASE_URL (repo convention) if not set explicitly.
os.environ.setdefault("DB_URL", os.environ.get("ADMIN_DATABASE_URL", ""))

# ---------------------------------------------------------------------------
# CONFIG — verify these match your actual table columns
#          (run 01_check_macro_coverage.py first to confirm)
# ---------------------------------------------------------------------------
SCHEMA      = "theeyebeta"
TABLE       = "macro_indicators"
FULL_TABLE  = f"{SCHEMA}.{TABLE}"

# ── Column name map ──────────────────────────────────────────────────────────
# EDIT these if your actual column names differ from defaults
COL_TS           = "ts"               # timestamptz  — observation date/time (hypertable dim)
COL_SERIES_CODE  = "series_code"      # text         — series identifier e.g. 'GDPC1'
COL_VALUE        = "value"            # numeric      — observation value
COL_SERIES_NAME  = "series_name"      # text         — human-readable name (nullable)
COL_SOURCE       = "source"           # text         — 'FRED' (nullable)
COL_UNITS        = "units"            # text         — units string (nullable)
COL_FREQUENCY    = "frequency"        # text         — 'daily','weekly','monthly','quarterly'
COL_SEASONAL_ADJ = "seasonal_adj"     # boolean      — seasonally adjusted? (nullable)
COL_VINTAGE_DATE = "vintage_date"     # date         — ALFRED realtime_start (nullable)
COL_IS_MANUAL    = "is_manual"        # boolean      — False for FRED auto
COL_INGESTED_AT  = "ingested_at"      # timestamptz  — when we pulled it

# The UNIQUE constraint that backs ON CONFLICT DO NOTHING
# Most likely: (series_code, ts) — adjust if yours is different
CONFLICT_COLS = f"({COL_SERIES_CODE}, {COL_TS})"
# ---------------------------------------------------------------------------

DEFAULT_START_DATE = "2010-01-01"   # 16 years of history
RATE_LIMIT_DELAY   = 0.5            # seconds between FRED requests (= 120/min safe)
BATCH_SIZE         = 5_000          # rows per DB INSERT batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("macro_backfill")


# ---------------------------------------------------------------------------
# FRED FETCH WITH RETRY
# ---------------------------------------------------------------------------

class FREDRateLimitError(Exception):
    pass


def make_fred_client() -> Fred:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        log.error("FRED_API_KEY environment variable not set.")
        log.error("Get a free key at: https://fredaccount.stlouisfed.org/apikey")
        sys.exit(1)
    return Fred(api_key=api_key)


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((FREDRateLimitError, ConnectionError)),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def fetch_series_latest(fred: Fred, code: str, start: str) -> pd.Series | None:
    """Fetch latest revision of a series (single-vintage; fast path)."""
    try:
        time.sleep(RATE_LIMIT_DELAY)
        series = fred.get_series(code, observation_start=start)
        return series
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            log.warning(f"Rate limited on {code}; backing off...")
            time.sleep(20)
            raise FREDRateLimitError(msg) from e
        if "400" in msg or "404" in msg:
            log.warning(f"Series {code} not found or bad request: {e}")
            return None
        raise


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

def get_connection():
    url = os.environ.get("DB_URL")
    if not url:
        log.error("DB_URL environment variable not set.")
        sys.exit(1)
    return psycopg.connect(url)


def get_already_present_codes(conn) -> set:
    sql = f"SELECT DISTINCT {COL_SERIES_CODE} FROM {FULL_TABLE};"
    with conn.cursor() as cur:
        cur.execute(sql)
        return {r[0] for r in cur.fetchall()}


def validate_columns_exist(conn):
    """Fail early if the column map is wrong."""
    sql = """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (SCHEMA, TABLE))
        actual = {r[0] for r in cur.fetchall()}

    required = {COL_TS, COL_SERIES_CODE, COL_VALUE}
    optional = {COL_SERIES_NAME, COL_SOURCE, COL_UNITS, COL_FREQUENCY,
                COL_SEASONAL_ADJ, COL_VINTAGE_DATE, COL_IS_MANUAL, COL_INGESTED_AT}
    missing_required = required - actual
    missing_optional = optional - actual

    if missing_required:
        log.error(f"REQUIRED columns missing from {FULL_TABLE}: {missing_required}")
        log.error("Edit the COL_* constants at the top of this script to match your schema.")
        sys.exit(1)

    if missing_optional:
        log.warning(f"Optional columns not present (will be skipped): {missing_optional}")

    return actual


def build_insert_sql(actual_cols: set) -> str:
    """Build INSERT statement using only columns that actually exist in the table."""
    # Always-required cols
    cols   = [COL_TS, COL_SERIES_CODE, COL_VALUE]
    values = ["%s",   "%s",            "%s"]

    # Optional cols — include only if present in actual schema
    optional_map = {
        COL_SERIES_NAME:  "%s",
        COL_SOURCE:       "%s",
        COL_UNITS:        "%s",
        COL_FREQUENCY:    "%s",
        COL_SEASONAL_ADJ: "%s",
        COL_VINTAGE_DATE: "%s",
        COL_IS_MANUAL:    "%s",
        COL_INGESTED_AT:  "NOW()",
    }
    for col, placeholder in optional_map.items():
        if col in actual_cols and col != COL_INGESTED_AT:
            cols.append(col)
            values.append(placeholder)
        elif col == COL_INGESTED_AT and col in actual_cols:
            cols.append(col)
            values.append("NOW()")

    col_str = ", ".join(cols)
    val_str = ", ".join(values)

    return (
        f"INSERT INTO {FULL_TABLE} ({col_str}) VALUES ({val_str})\n"
        f"ON CONFLICT {CONFLICT_COLS} DO NOTHING;"
    )


def upsert_batch(conn, sql: str, rows: list, dry_run: bool) -> int:
    if not rows:
        return 0
    if dry_run:
        log.info(f"  [DRY RUN] Would insert {len(rows)} rows")
        return len(rows)

    # Remove the NOW() placeholder from parameterized cols count
    # (NOW() is a SQL function, not a parameter)
    param_count = sql.count("%s")
    rows_trimmed = [r[:param_count] for r in rows]

    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows_trimmed)
        conn.commit()
        return len(rows)
    except Exception as e:
        conn.rollback()
        log.error(f"DB insert failed: {e}")
        raise


# ---------------------------------------------------------------------------
# ROW BUILDERS
# ---------------------------------------------------------------------------

def build_rows_latest(series: pd.Series, meta: dict, actual_cols: set) -> list:
    """Build row tuples from a latest-revision pandas Series."""
    rows = []
    for obs_date, value in series.items():
        if pd.isna(value):
            continue
        ts = pd.Timestamp(obs_date).to_pydatetime()
        row = [ts, meta["code"], float(value)]
        if COL_SERIES_NAME in actual_cols:
            row.append(meta["name"])
        if COL_SOURCE in actual_cols:
            row.append("FRED")
        if COL_UNITS in actual_cols:
            row.append(meta.get("units", ""))
        if COL_FREQUENCY in actual_cols:
            row.append(meta.get("freq", ""))
        if COL_SEASONAL_ADJ in actual_cols:
            row.append(meta.get("seasonal_adj"))
        if COL_VINTAGE_DATE in actual_cols:
            row.append(None)  # no vintage for latest
        if COL_IS_MANUAL in actual_cols:
            row.append(False)
        rows.append(tuple(row))
    return rows


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Backfill FRED macro series into TheEyeBeta")
    p.add_argument("--series", nargs="*", help="Specific FRED codes to process (default: all missing)")
    p.add_argument("--refresh", action="store_true", help="Re-fetch even if series already in DB")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen without writing to DB")
    p.add_argument("--vintage-only", action="store_true", help="Restrict to revision-critical series (still latest-revision fetch; vintage storage disabled)")
    p.add_argument("--start", default=DEFAULT_START_DATE, help=f"Start date for history (default: {DEFAULT_START_DATE})")
    return p.parse_args()


def main():
    args = parse_args()
    conn = get_connection()

    log.info(f"Connected to DB. Target table: {FULL_TABLE}")

    actual_cols = validate_columns_exist(conn)
    insert_sql  = build_insert_sql(actual_cols)
    log.info(f"Insert SQL (first 120 chars): {insert_sql[:120]}...")

    present_codes = get_already_present_codes(conn)
    log.info(f"Series already in DB: {len(present_codes)}")

    fred = make_fred_client()

    # Determine target list
    if args.series:
        target = [SERIES_BY_CODE[c] for c in args.series if c in SERIES_BY_CODE]
        not_found = [c for c in args.series if c not in SERIES_BY_CODE]
        if not_found:
            log.warning(f"Codes not in registry (will skip): {not_found}")
    elif args.vintage_only:
        log.warning("--vintage-only: ALFRED multi-vintage storage is disabled "
                    "(no vintage_date column); fetching these latest-revision only.")
        target = [SERIES_BY_CODE[c] for c in REVISION_CRITICAL if c in SERIES_BY_CODE]
    else:
        target = FRED_SERIES

    if not args.refresh:
        to_process = [s for s in target if s["code"] not in present_codes]
        log.info(f"Skipping {len(target) - len(to_process)} already-present series (use --refresh to force)")
    else:
        to_process = target
        log.info(f"--refresh mode: will re-fetch all {len(to_process)} target series")

    if not to_process:
        log.info("Nothing to do — all target series are already in the database.")
        conn.close()
        return

    log.info(f"\nWill process {len(to_process)} series, start date: {args.start}")
    if args.dry_run:
        log.info("DRY RUN MODE — no data will be written")

    total_rows = 0
    errors = []

    for i, meta in enumerate(to_process, 1):
        code = meta["code"]
        # vintage / ALFRED mode disabled: schema has no vintage_date column and the
        # unique key is (series_code, ts), so every series is fetched latest-revision.
        log.info(f"[{i:>3}/{len(to_process)}] {code:<30} (latest revision)")

        try:
            raw = fetch_series_latest(fred, code, args.start)
            if raw is None or raw.empty:
                log.warning(f"  Skipping {code} — no data returned")
                continue
            rows = build_rows_latest(raw, meta, actual_cols)

            if not rows:
                log.warning(f"  {code}: 0 valid rows after cleaning — skipping")
                continue

            inserted = upsert_batch(conn, insert_sql, rows, args.dry_run)
            total_rows += inserted
            log.info(f"  ✓ {code}: {inserted} rows {'(would insert)' if args.dry_run else 'inserted'}")

        except KeyboardInterrupt:
            log.warning("\nInterrupted — committing progress so far.")
            break
        except Exception as e:
            log.error(f"  ✗ {code}: FAILED — {e}")
            errors.append((code, str(e)))
            continue

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("\n" + "═"*50)
    log.info(f"  DONE — {total_rows:,} rows {'would be ' if args.dry_run else ''}written")
    log.info(f"  Processed: {i}/{len(to_process)} series")
    if errors:
        log.warning(f"  Errors on {len(errors)} series:")
        for code, err in errors:
            log.warning(f"    {code}: {err}")
        log.warning("  Re-run the script — errors are idempotent (ON CONFLICT DO NOTHING)")
    log.info("═"*50)

    conn.close()


if __name__ == "__main__":
    main()
