"""
01_check_macro_coverage.py
==========================
RUN THIS FIRST — before any ingestor.

What it does:
  1. Connects to theeyebeta and inspects the actual schema of macro_indicators
  2. Lists every distinct series_code currently in the table
  3. Diffs against the full 155-series registry
  4. Prints three output lists:
       - ALREADY PRESENT (skip — or optionally refresh)
       - MISSING AUTO   (02_fred_macro_backfill.py will add these)
       - MISSING MANUAL (03_manual_file_ingestor.py will add these once you supply the CSV)
  5. Reports staleness for each present series (days since last observation)
  6. Prints the actual DB column names so you can validate the ingestor assumptions

Usage:
  export DB_URL="postgresql://user:pass@host:5432/TheEyeBeta2025Live"
  python 01_check_macro_coverage.py

  # Or pass inline:
  DB_URL="postgresql://..." python 01_check_macro_coverage.py
"""

import os
import sys
from datetime import UTC, datetime

import psycopg
from macro_series_registry import (
    ALL_FRED_CODES,
    ALL_MANUAL_CODES,
    SERIES_BY_CODE,
)
from psycopg.rows import dict_row

# DB_URL falls back to ADMIN_DATABASE_URL (repo convention) if not set explicitly.
os.environ.setdefault("DB_URL", os.environ.get("ADMIN_DATABASE_URL", ""))

# ---------------------------------------------------------------------------
# CONFIG — edit if your column names differ from defaults
# ---------------------------------------------------------------------------
SCHEMA = "theeyebeta"
TABLE = "macro_indicators"
SERIES_COL = "series_code"  # ← the column holding the series identifier
TS_COL = "ts"  # ← the hypertable time dimension column
VALUE_COL = "value"  # ← the numeric observation value
# ---------------------------------------------------------------------------

FULL_TABLE = f"{SCHEMA}.{TABLE}"
STALE_WARN_DAYS = {
    "daily": 3,
    "weekly": 10,
    "monthly": 35,
    "quarterly": 95,
}

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def get_connection():
    url = os.environ.get("DB_URL")
    if not url:
        print(f"{RED}ERROR: DB_URL environment variable not set.{RESET}")
        print('  export DB_URL="postgresql://user:pass@host:5432/TheEyeBeta2025Live"')
        sys.exit(1)
    return psycopg.connect(url)


def discover_schema(conn):
    """Return (column_names, comment_on_time_col)"""
    sql = """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (SCHEMA, TABLE))
        rows = cur.fetchall()

    if not rows:
        print(f"{RED}ERROR: Table {FULL_TABLE} not found in the database!{RESET}")
        print("  Verify the schema and table name match your Alembic migrations.")
        sys.exit(1)

    return rows


def check_hypertable(conn):
    sql = """
        SELECT hypertable_name, num_dimensions, num_chunks
        FROM timescaledb_information.hypertables
        WHERE hypertable_schema = %s AND hypertable_name = %s;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (SCHEMA, TABLE))
        return cur.fetchone()


def get_present_series(conn):
    """Returns dict: series_code → {last_ts, count, min_ts}"""
    sql = f"""
        SELECT
            {SERIES_COL} AS code,
            MAX({TS_COL}) AS last_ts,
            MIN({TS_COL}) AS first_ts,
            COUNT(*) AS row_count
        FROM {FULL_TABLE}
        GROUP BY {SERIES_COL}
        ORDER BY {SERIES_COL};
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return {r["code"]: r for r in rows}


def staleness_flag(series_code, last_ts):
    meta = SERIES_BY_CODE.get(series_code)
    if not meta or not last_ts:
        return ""
    freq = meta.get("freq", "monthly")
    threshold = STALE_WARN_DAYS.get(freq, 35)
    now = datetime.now(UTC)
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=UTC)
    days_ago = (now - last_ts).days
    if days_ago > threshold:
        return f" {RED}⚠ STALE ({days_ago}d){RESET}"
    return f" {GREEN}✓ ({days_ago}d ago){RESET}"


def main():
    print(f"\n{BOLD}{CYAN}══════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}{CYAN}  TheEyeBeta Macro Coverage Check — {datetime.now():%Y-%m-%d %H:%M}{RESET}")
    print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════{RESET}\n")

    conn = get_connection()

    # ── 1. Actual schema ────────────────────────────────────────────────────
    print(f"{BOLD}[1] TABLE SCHEMA — {FULL_TABLE}{RESET}")
    schema_cols = discover_schema(conn)
    for col in schema_cols:
        nullable = "" if col["is_nullable"] == "YES" else " NOT NULL"
        print(f"    {col['column_name']:<35} {col['data_type']}{nullable}")

    # Validate expected columns exist
    actual_cols = {c["column_name"] for c in schema_cols}
    missing_expected = []
    for col in [SERIES_COL, TS_COL, VALUE_COL]:
        if col not in actual_cols:
            missing_expected.append(col)
    if missing_expected:
        print(f"\n  {RED}WARNING: Expected columns NOT found: {missing_expected}{RESET}")
        print("  Edit the CONFIG section at the top of this script and the ingestors.")
    else:
        print(
            f"\n  {GREEN}✓ All expected key columns confirmed: {SERIES_COL}, {TS_COL}, {VALUE_COL}{RESET}"
        )

    # ── 2. Hypertable info ───────────────────────────────────────────────────
    print(f"\n{BOLD}[2] TIMESCALEDB STATUS{RESET}")
    ht = check_hypertable(conn)
    if ht:
        print(
            f"  ✓ Confirmed hypertable: {ht['num_dimensions']} dimension(s), {ht['num_chunks']} chunk(s)"
        )
    else:
        print(
            f"  {YELLOW}⚠ Not registered as a TimescaleDB hypertable — proceed with caution{RESET}"
        )

    # ── 3. What's already in the DB ─────────────────────────────────────────
    print(f"\n{BOLD}[3] SERIES CURRENTLY IN DATABASE{RESET}")
    present = get_present_series(conn)
    print(f"  Total distinct series found: {len(present)}\n")

    for code, stats in sorted(present.items()):
        meta = SERIES_BY_CODE.get(code, {})
        name = meta.get("name", "(unknown — not in registry)")
        flag = staleness_flag(code, stats["last_ts"])
        rows = stats["row_count"]
        first = stats["first_ts"].strftime("%Y-%m-%d") if stats["first_ts"] else "?"
        last = stats["last_ts"].strftime("%Y-%m-%d") if stats["last_ts"] else "?"
        print(f"  {GREEN}●{RESET} {code:<30} {rows:>8,} rows  {first} → {last}{flag}")
        if meta:
            print(f"    {name}")

    # ── 4. Coverage diff ────────────────────────────────────────────────────
    present_codes = set(present.keys())
    target_fred = set(ALL_FRED_CODES)
    target_manual = set(ALL_MANUAL_CODES)
    all_target = target_fred | target_manual

    in_db_and_registered = present_codes & all_target
    in_db_not_registered = present_codes - all_target
    missing_auto = target_fred - present_codes
    missing_manual = target_manual - present_codes

    # ── 5. Already covered ───────────────────────────────────────────────────
    print(f"\n{BOLD}[4] ALREADY COVERED — {len(in_db_and_registered)} series{RESET}")
    for code in sorted(in_db_and_registered):
        name = SERIES_BY_CODE[code]["name"]
        print(f"  {GREEN}✓{RESET} {code:<30} {name}")

    if in_db_not_registered:
        print(f"\n{BOLD}[4b] IN DB BUT NOT IN REGISTRY — {len(in_db_not_registered)} series{RESET}")
        print(f"  {YELLOW}These exist in the DB but are not in the macro_series_registry.{RESET}")
        print(
            f"  {YELLOW}They may be legacy series from your old worker. Leave them alone unless confirmed dead.{RESET}"
        )
        for code in sorted(in_db_not_registered):
            stats = present[code]
            print(f"  {YELLOW}?{RESET} {code}")

    # ── 6. Missing auto (FRED) ────────────────────────────────────────────────
    print(f"\n{BOLD}[5] MISSING — AUTOMATED (FRED){RESET}  → run 02_fred_macro_backfill.py")
    print(f"  {len(missing_auto)} series to add\n")
    by_cat = {}
    for code in missing_auto:
        meta = SERIES_BY_CODE[code]
        by_cat.setdefault(meta["category"], []).append(code)
    for cat in sorted(by_cat):
        print(f"  {CYAN}{cat.upper()}{RESET}")
        for code in sorted(by_cat[cat]):
            print(f"    {RED}○{RESET} {code:<30} {SERIES_BY_CODE[code]['name']}")

    # ── 7. Missing manual ─────────────────────────────────────────────────────
    print(
        f"\n{BOLD}[6] MISSING — MANUAL (licensed/no free API){RESET}  → fill manual_macro_template.csv + run 03_manual_file_ingestor.py"
    )
    print(f"  {len(missing_manual)} series to add manually\n")
    for code in sorted(missing_manual):
        meta = SERIES_BY_CODE[code]
        print(f"  {YELLOW}○{RESET} {code:<30} {meta['name']}")
        print(f"    Download from: {meta['manual_url']}")

    # ── 8. Summary ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'━' * 54}{RESET}")
    print(f"{BOLD}  SUMMARY{RESET}")
    print(f"{'━' * 54}")
    print(f"  Target universe:     {len(all_target):>4} series")
    print(f"  Already in DB:       {len(in_db_and_registered):>4} series")
    pct_auto = 100 * (len(target_fred - missing_auto) / len(target_fred)) if target_fred else 0
    print(
        f"  FRED coverage:       {pct_auto:.0f}%  ({len(target_fred - missing_auto)}/{len(target_fred)} automated)"
    )
    print(f"  Missing (auto):      {len(missing_auto):>4} — run 02_fred_macro_backfill.py")
    print(
        f"  Missing (manual):    {len(missing_manual):>4} — fill CSV + run 03_manual_file_ingestor.py"
    )
    print(f"{'━' * 54}\n")

    conn.close()


if __name__ == "__main__":
    main()
