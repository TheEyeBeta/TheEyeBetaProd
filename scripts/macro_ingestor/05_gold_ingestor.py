"""
05_gold_ingestor.py
===================
Fetches gold spot price via yfinance (GC=F = COMEX front-month gold futures)
and ingests into theeyebeta.macro_indicators.

Why yfinance and not FRED:
  FRED discontinued both London gold fixing series (AM + PM) in 2024.
  GC=F (COMEX continuous futures) is the best freely available proxy.
  Correlation to spot gold is >0.999 intraday.

Usage:
  export DB_URL="..."   # or ADMIN_DATABASE_URL
  python 05_gold_ingestor.py              # full history from 2010
  python 05_gold_ingestor.py --refresh    # last 30 days only (for cron)
  python 05_gold_ingestor.py --dry-run    # validate without writing

Add to cron alongside 04_macro_refresh.py — run nightly after US close.
Systemd timer: see deploy/systemd/theeye-macro-refresh.{service,timer}.
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg
import yfinance as yf

# ---------------------------------------------------------------------------
SCHEMA = "theeyebeta"
TABLE = "macro_indicators"
FULL_TABLE = f"{SCHEMA}.{TABLE}"

SERIES_CODE = "GOLDPMGBD228NLBM"  # Keep the FRED ID as the canonical code
SERIES_NAME = "Gold Price (COMEX GC=F front-month)"
SOURCE = "yfinance/COMEX"
UNITS = "USD per Troy Ounce"
FREQUENCY = "daily"

TICKER = "GC=F"  # COMEX gold continuous futures
DEFAULT_START = "2010-01-01"
REFRESH_DAYS = 30  # days to fetch in --refresh mode

CONFLICT_COLS = "(series_code, ts)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("gold_ingestor")
# ---------------------------------------------------------------------------


def get_conn():
    url = os.environ.get("DB_URL") or os.environ.get("ADMIN_DATABASE_URL")
    if not url:
        log.error("Set DB_URL or ADMIN_DATABASE_URL")
        sys.exit(1)
    return psycopg.connect(url)


def get_actual_cols(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
        """,
            (SCHEMA, TABLE),
        )
        return {r[0] for r in cur.fetchall()}


def build_insert(actual_cols: set[str]) -> str:
    cols = ["ts", "series_code", "value"]
    values = ["%s", "%s", "%s"]
    optional = {
        "series_name": SERIES_NAME,
        "source": SOURCE,
        "units": UNITS,
        "frequency": FREQUENCY,
        "is_manual": False,
    }
    for col in optional:
        if col in actual_cols:
            cols.append(col)
            values.append("%s")
    if "ingested_at" in actual_cols:
        cols.append("ingested_at")
        values.append("NOW()")
    col_str = ", ".join(cols)
    val_str = ", ".join(values)
    return (
        f"INSERT INTO {FULL_TABLE} ({col_str}) VALUES ({val_str}) "
        f"ON CONFLICT {CONFLICT_COLS} DO NOTHING"
    )


def fetch_gold(start: str) -> pd.DataFrame:
    log.info("Fetching %s from %s via yfinance...", TICKER, start)
    ticker = yf.Ticker(TICKER)
    df = ticker.history(start=start, auto_adjust=True)
    if df.empty:
        log.error("yfinance returned empty data — check ticker or network")
        sys.exit(1)
    log.info(
        "Fetched %d rows (%s → %s)",
        len(df),
        df.index[0].date(),
        df.index[-1].date(),
    )
    return df


def build_rows(df: pd.DataFrame, actual_cols: set[str]) -> list[tuple]:
    optional_vals = {
        "series_name": SERIES_NAME,
        "source": SOURCE,
        "units": UNITS,
        "frequency": FREQUENCY,
        "is_manual": False,
    }
    rows = []
    for ts, row in df.iterrows():
        close = row.get("Close")
        if pd.isna(close) or close <= 0:
            continue
        ts_dt = ts.to_pydatetime()
        r: list = [ts_dt, SERIES_CODE, float(close)]
        for col, val in optional_vals.items():
            if col in actual_cols:
                r.append(val)
        rows.append(tuple(r))
    return rows


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--refresh",
        action="store_true",
        help=f"Only fetch last {REFRESH_DAYS} days",
    )
    p.add_argument("--dry-run", action="store_true", help="Validate without writing to DB")
    return p.parse_args()


def main():
    args = parse_args()

    start = (
        (datetime.now(UTC) - timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%d")
        if args.refresh
        else DEFAULT_START
    )

    df = fetch_gold(start)
    conn = get_conn()
    actual_cols = get_actual_cols(conn)
    insert_sql = build_insert(actual_cols)
    rows = build_rows(df, actual_cols)

    if not rows:
        log.warning("No valid rows to insert")
        conn.close()
        return

    log.info(
        "%d rows to submit (new rows = submitted minus ON CONFLICT skips)",
        len(rows),
    )

    if args.dry_run:
        log.info("[DRY RUN] Would submit %d rows. First: %s", len(rows), rows[0])
        conn.close()
        return

    try:
        with conn.cursor() as cur:
            cur.executemany(insert_sql, rows)
        conn.commit()
        log.info("Done — %d rows submitted for %s", len(rows), SERIES_CODE)
    except Exception:
        conn.rollback()
        log.exception("Insert failed")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
