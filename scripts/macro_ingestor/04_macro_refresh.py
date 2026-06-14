"""
04_macro_refresh.py
===================
Incremental refresh — fetches only recent observations per series frequency.
Designed to run daily from cron or systemd. Safe to run multiple times (idempotent).

Logic:
  - Daily series   → last 7 days
  - Weekly series  → last 21 days
  - Monthly series → last 90 days
  - Quarterly      → last 180 days

Uses ON CONFLICT DO NOTHING — re-running is always safe.

Usage:
  python 04_macro_refresh.py                  # refresh all automated series
  python 04_macro_refresh.py --series DGS10   # single series
  python 04_macro_refresh.py --dry-run        # show what would be fetched

Cron (daily at 21:00 UTC, after US market close):
  0 21 * * * cd /path/to/scripts/macro_ingestor && \
    DB_URL=$ADMIN_DATABASE_URL FRED_API_KEY=xxx python 04_macro_refresh.py \
    >> /var/log/macro_refresh.log 2>&1

Systemd timer: see deploy/systemd/theeye-macro-refresh.{service,timer}.
"""

import argparse
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg
from fredapi import Fred
from macro_series_registry import FRED_SERIES, SERIES_BY_CODE
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCHEMA     = "theeyebeta"
TABLE      = "macro_indicators"
FULL_TABLE = f"{SCHEMA}.{TABLE}"

COL_TS          = "ts"
COL_SERIES_CODE = "series_code"
COL_VALUE       = "value"
COL_SOURCE      = "source"

CONFLICT_COLS = f"({COL_SERIES_CODE}, {COL_TS})"

# How far back to fetch per frequency
LOOKBACK = {
    "daily":     7,
    "weekly":    21,
    "monthly":   90,
    "quarterly": 180,
}

RATE_LIMIT_DELAY = 0.6   # seconds between FRED requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("macro_refresh")

# ---------------------------------------------------------------------------
# FRED
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    pass


def make_fred():
    key = os.environ.get("FRED_API_KEY")
    if not key:
        log.error("FRED_API_KEY not set")
        sys.exit(1)
    return Fred(api_key=key)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    retry=retry_if_exception_type((RateLimitError, ConnectionError)),
    before_sleep=before_sleep_log(log, logging.WARNING),
)
def fetch(fred, code, start_date):
    try:
        time.sleep(RATE_LIMIT_DELAY)
        series = fred.get_series(code, observation_start=start_date.strftime("%Y-%m-%d"))
        return series
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate limit" in msg.lower():
            time.sleep(20)
            raise RateLimitError(msg) from e
        if "400" in msg or "404" in msg:
            return None
        raise


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def get_conn():
    url = os.environ.get("DB_URL") or os.environ.get("ADMIN_DATABASE_URL")
    if not url:
        log.error("Set DB_URL or ADMIN_DATABASE_URL")
        sys.exit(1)
    return psycopg.connect(url)


def get_actual_cols(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
        """, (SCHEMA, TABLE))
        return {r[0] for r in cur.fetchall()}


def build_insert(actual_cols):
    cols   = [COL_TS, COL_SERIES_CODE, COL_VALUE]
    values = ["%s",   "%s",            "%s"]
    if COL_SOURCE in actual_cols:
        cols.append(COL_SOURCE)
        values.append("%s")
    col_str = ", ".join(cols)
    val_str = ", ".join(values)
    return (
        f"INSERT INTO {FULL_TABLE} ({col_str}) VALUES ({val_str})\n"
        f"ON CONFLICT {CONFLICT_COLS} DO NOTHING"
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--series", nargs="*", help="Specific codes to refresh")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    now  = datetime.now(UTC)

    conn        = get_conn()
    actual_cols = get_actual_cols(conn)
    insert_sql  = build_insert(actual_cols)
    has_source  = COL_SOURCE in actual_cols

    fred = make_fred()

    target = FRED_SERIES
    if args.series:
        target = [SERIES_BY_CODE[c] for c in args.series if c in SERIES_BY_CODE]

    log.info(f"Refreshing {len(target)} series | dry_run={args.dry_run}")

    total_inserted = 0
    errors = []

    for meta in target:
        code    = meta["code"]
        freq    = meta.get("freq", "monthly")
        days    = LOOKBACK.get(freq, 90)
        start   = (now - timedelta(days=days)).date()

        try:
            series = fetch(fred, code, start)
        except Exception as e:  # noqa: BLE001 — a dead/transient series must not abort the whole run
            log.error(f"  ✗ {code}: fetch failed — {e}")
            errors.append(code)
            continue
        if series is None or series.empty:
            continue

        rows = []
        for obs_date, value in series.items():
            if pd.isna(value):
                continue
            ts = pd.Timestamp(obs_date).to_pydatetime()
            row = [ts, code, float(value)]
            if has_source:
                row.append("FRED")
            rows.append(tuple(row))

        if not rows:
            continue

        if args.dry_run:
            log.info(f"  [DRY] {code}: {len(rows)} rows from {start}")
            continue

        try:
            with conn.cursor() as cur:
                cur.executemany(insert_sql, rows)
            conn.commit()
            total_inserted += len(rows)
            log.info(f"  ✓ {code:<30} {len(rows)} rows from {start}")
        except Exception as e:
            conn.rollback()
            log.error(f"  ✗ {code}: {e}")
            errors.append(code)

    log.info(f"\nDone — {total_inserted} rows inserted")
    if errors:
        log.warning(f"Failed: {errors}")

    conn.close()


if __name__ == "__main__":
    main()
