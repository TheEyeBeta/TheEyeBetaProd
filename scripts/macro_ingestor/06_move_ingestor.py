"""
06_move_ingestor.py
===================
Fetches the MOVE index (Merrill Lynch Option Volatility Estimate — the "bond VIX")
via yfinance (^MOVE) and ingests into theeyebeta.macro_indicators.

Why yfinance and not a manual download:
  ICE/BofA charge for MOVE redistribution, so there is no free FRED series and the
  template flow (03_manual_file_ingestor.py) treated it as a manual CSV chore. But
  Yahoo Finance carries ^MOVE for free, so yfinance can pull it the same way
  05_gold_ingestor.py pulls GC=F — making MOVE fully self-sustaining (no manual step).

Usage:
  export DB_URL="..."   # or ADMIN_DATABASE_URL
  python 06_move_ingestor.py              # full history
  python 06_move_ingestor.py --refresh    # last 30 days only (for cron)
  python 06_move_ingestor.py --dry-run    # validate without writing

Add to cron alongside 04_macro_refresh.py + 05_gold_ingestor.py — run nightly after
US close. Systemd unit: see deploy/systemd/theeye-macro-refresh.service.
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

SERIES_CODE = "MOVE_INDEX"  # matches macro_series_registry.py MANUAL_SERIES
SERIES_NAME = "MOVE Index (Treasury Volatility)"
SOURCE = "yfinance/ICE BofA"
UNITS = "Index"
FREQUENCY = "daily"

TICKER = "^MOVE"  # ICE BofA MOVE index on Yahoo Finance
DEFAULT_START = "1988-01-01"  # Yahoo returns whatever history it has from here
REFRESH_DAYS = 30  # days to fetch in --refresh mode

CONFLICT_COLS = "(series_code, ts)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("move_ingestor")
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


def fetch_move(start: str) -> pd.DataFrame:
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

    df = fetch_move(start)
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
