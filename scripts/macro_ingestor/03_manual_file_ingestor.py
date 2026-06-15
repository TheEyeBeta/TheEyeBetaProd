"""
03_manual_file_ingestor.py
==========================
Ingests manually downloaded data (ISM PMI, Conference Board, NAHB, ADP, MOVE, etc.)
into theeyebeta.macro_indicators.

HOW IT WORKS:
  1. You download data from the source website (see manual_macro_template.csv for URLs)
  2. You fill in the template CSV (or use your own CSV with the same column structure)
  3. Run this script — it validates, deduplicates, and upserts into the DB
  4. Already-present rows are skipped (ON CONFLICT DO NOTHING — idempotent)

SUPPORTED INPUT FORMATS:
  - CSV  (.csv)
  - Excel (.xlsx, .xls) — specify --sheet if needed (requires openpyxl)

Usage:
  pip install psycopg[binary] pandas openpyxl

  export DB_URL="postgresql://user:pass@host:5432/TheEyeBeta2025Live"

  # Ingest from CSV:
  python 03_manual_file_ingestor.py --file manual_macro_data.csv

  # Ingest from Excel, specific sheet:
  python 03_manual_file_ingestor.py --file macro_downloads.xlsx --sheet "ISM Data"

  # Dry run — validate without writing:
  python 03_manual_file_ingestor.py --file manual_macro_data.csv --dry-run

  # Only ingest specific series codes from the file:
  python 03_manual_file_ingestor.py --file data.csv --series ISM_MFG_PMI CB_LEI

REQUIRED CSV COLUMNS (minimum):
  series_code   : e.g. ISM_MFG_PMI
  obs_date      : observation date — YYYY-MM-DD
  value         : numeric value

OPTIONAL CSV COLUMNS (all passed through to DB if columns exist there):
  series_name   : human readable name
  source        : e.g. ISM, CONFERENCE_BOARD
  units         : units string
  frequency     : monthly / weekly / daily / quarterly
  seasonal_adj  : TRUE / FALSE
  vintage_date  : YYYY-MM-DD (leave blank for manual data — none available)
  notes         : any notes (written to remediation_notes if column exists)
"""

import argparse
import logging
import os
import sys

import pandas as pd
import psycopg
from macro_series_registry import MANUAL_SERIES, SERIES_BY_CODE

# DB_URL falls back to ADMIN_DATABASE_URL (repo convention) if not set explicitly.
os.environ.setdefault("DB_URL", os.environ.get("ADMIN_DATABASE_URL", ""))

# ---------------------------------------------------------------------------
# CONFIG — must match your actual table
# ---------------------------------------------------------------------------
SCHEMA     = "theeyebeta"
TABLE      = "macro_indicators"
FULL_TABLE = f"{SCHEMA}.{TABLE}"

# Column names — MUST match what 01_check_macro_coverage.py reported
COL_TS            = "ts"
COL_SERIES_CODE   = "series_code"
COL_VALUE         = "value"
COL_SERIES_NAME   = "series_name"
COL_SOURCE        = "source"
COL_UNITS         = "units"
COL_FREQUENCY     = "frequency"
COL_SEASONAL_ADJ  = "seasonal_adj"
COL_VINTAGE_DATE  = "vintage_date"
COL_IS_MANUAL     = "is_manual"
COL_INGESTED_AT   = "ingested_at"
COL_REMEDIATION   = "remediation_notes"   # may not exist — checked at runtime

CONFLICT_COLS = f"({COL_SERIES_CODE}, {COL_TS})"

BATCH_SIZE = 2_000
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("manual_ingestor")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def get_connection():
    url = os.environ.get("DB_URL")
    if not url:
        log.error("DB_URL not set. export DB_URL='postgresql://user:pass@host/db'")
        sys.exit(1)
    return psycopg.connect(url)


def get_actual_columns(conn) -> set:
    sql = """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (SCHEMA, TABLE))
        return {r[0] for r in cur.fetchall()}


def build_insert_sql(actual_cols: set) -> str:
    cols   = [COL_TS, COL_SERIES_CODE, COL_VALUE]
    values = ["%s",   "%s",            "%s"]

    optional = [
        COL_SERIES_NAME, COL_SOURCE, COL_UNITS,
        COL_FREQUENCY, COL_SEASONAL_ADJ, COL_VINTAGE_DATE, COL_IS_MANUAL,
    ]
    for col in optional:
        if col in actual_cols:
            cols.append(col)
            values.append("%s")

    if COL_INGESTED_AT in actual_cols:
        cols.append(COL_INGESTED_AT)
        values.append("NOW()")

    if COL_REMEDIATION in actual_cols:
        cols.append(COL_REMEDIATION)
        values.append("%s")

    col_str = ", ".join(cols)
    val_str = ", ".join(values)

    return (
        f"INSERT INTO {FULL_TABLE} ({col_str}) VALUES ({val_str})\n"
        f"ON CONFLICT {CONFLICT_COLS} DO NOTHING;"
    )


def get_existing_keys(conn, codes: list) -> set:
    """Returns set of (series_code, obs_date_str) already in DB."""
    if not codes:
        return set()
    sql = f"""
        SELECT {COL_SERIES_CODE}, {COL_TS}::date::text
        FROM {FULL_TABLE}
        WHERE {COL_SERIES_CODE} = ANY(%s);
    """
    with conn.cursor() as cur:
        cur.execute(sql, (codes,))
        return {(r[0], r[1]) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# FILE LOADING & VALIDATION
# ---------------------------------------------------------------------------

REQUIRED_CSV_COLS = {"series_code", "obs_date", "value"}

MANUAL_CODE_SET = {s["code"] for s in MANUAL_SERIES}


def load_file(filepath: str, sheet: str = None) -> pd.DataFrame:
    ext = filepath.lower().split(".")[-1]
    if ext == "csv":
        df = pd.read_csv(filepath, dtype=str)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(filepath, sheet_name=sheet or 0, dtype=str)
    else:
        log.error(f"Unsupported file type: .{ext} — use .csv or .xlsx")
        sys.exit(1)

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Check required columns, parse types, drop bad rows, return clean df."""
    missing_cols = REQUIRED_CSV_COLS - set(df.columns)
    if missing_cols:
        log.error(f"Required columns missing from file: {missing_cols}")
        log.error(f"File has columns: {list(df.columns)}")
        log.error("Required: series_code, obs_date, value")
        sys.exit(1)

    original_len = len(df)

    # Strip whitespace
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

    # Drop comment/instruction rows (series_code starts with #)
    df = df[~df["series_code"].str.startswith("#", na=True)]

    # Drop rows with no series_code or value
    df = df.dropna(subset=["series_code", "value"])
    df = df[df["series_code"] != ""]
    df = df[df["value"] != ""]

    # Parse obs_date
    df["obs_date"] = pd.to_datetime(df["obs_date"], errors="coerce")
    bad_dates = df["obs_date"].isna().sum()
    if bad_dates > 0:
        log.warning(f"Dropping {bad_dates} rows with unparseable dates")
        df = df.dropna(subset=["obs_date"])

    # Parse value — numeric only
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    bad_vals = df["value"].isna().sum()
    if bad_vals > 0:
        log.warning(f"Dropping {bad_vals} rows with non-numeric values")
        df = df.dropna(subset=["value"])

    # Parse seasonal_adj if present
    if "seasonal_adj" in df.columns:
        df["seasonal_adj"] = df["seasonal_adj"].str.upper().map(
            {"TRUE": True, "FALSE": False, "YES": True, "NO": False, "1": True, "0": False}
        )

    log.info(f"File: {original_len} raw rows → {len(df)} valid rows after cleaning")

    # Warn about codes not in registry
    unknown = set(df["series_code"].unique()) - set(SERIES_BY_CODE.keys())
    if unknown:
        log.warning(f"Codes in file not in registry (will still be ingested): {unknown}")
        log.warning("Consider adding them to macro_series_registry.py MANUAL_SERIES")

    return df


def enrich_from_registry(row: pd.Series) -> dict:
    """Fill in metadata from the registry if the CSV didn't provide it."""
    code = row["series_code"]
    meta = SERIES_BY_CODE.get(code, {})
    return {
        "series_name":  row.get("series_name")  or meta.get("name", ""),
        "source":       row.get("source")        or meta.get("source", "MANUAL"),
        "units":        row.get("units")         or meta.get("units", ""),
        "frequency":    row.get("frequency")     or meta.get("freq", ""),
        "seasonal_adj": row.get("seasonal_adj")  if not pd.isna(row.get("seasonal_adj", None)) else meta.get("seasonal_adj"),
        "notes":        row.get("notes", ""),
    }


def build_row_tuple(row: pd.Series, actual_cols: set) -> tuple:
    ts  = row["obs_date"].to_pydatetime()
    val = float(row["value"])
    r   = [ts, row["series_code"], val]
    enriched = enrich_from_registry(row)

    if COL_SERIES_NAME in actual_cols:
        r.append(enriched["series_name"] or None)
    if COL_SOURCE in actual_cols:
        r.append(enriched["source"] or "MANUAL")
    if COL_UNITS in actual_cols:
        r.append(enriched["units"] or None)
    if COL_FREQUENCY in actual_cols:
        r.append(enriched["frequency"] or None)
    if COL_SEASONAL_ADJ in actual_cols:
        r.append(enriched.get("seasonal_adj"))
    if COL_VINTAGE_DATE in actual_cols:
        r.append(None)  # manual data has no vintage
    if COL_IS_MANUAL in actual_cols:
        r.append(True)
    # COL_INGESTED_AT is NOW() in SQL — not a parameter
    if COL_REMEDIATION in actual_cols:
        r.append(enriched["notes"] or None)

    return tuple(r)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Ingest manually downloaded macro data")
    p.add_argument("--file",    required=True, help="Path to CSV or Excel file")
    p.add_argument("--sheet",   default=None,  help="Excel sheet name (default: first sheet)")
    p.add_argument("--series",  nargs="*",     help="Only ingest these series codes from the file")
    p.add_argument("--dry-run", action="store_true", help="Validate file and show what would be inserted, no DB writes")
    return p.parse_args()


def main():
    args = parse_args()

    log.info(f"Loading file: {args.file}")
    df = load_file(args.file, args.sheet)
    df = validate_dataframe(df)

    if args.series:
        df = df[df["series_code"].isin(args.series)]
        log.info(f"Filtered to {len(args.series)} specified series: {len(df)} rows remaining")

    if df.empty:
        log.info("No valid rows to process after filtering.")
        return

    conn = get_connection()
    actual_cols = get_actual_columns(conn)

    missing_required = {COL_TS, COL_SERIES_CODE, COL_VALUE} - actual_cols
    if missing_required:
        log.error(f"Table {FULL_TABLE} is missing required columns: {missing_required}")
        log.error("Run 01_check_macro_coverage.py to inspect the actual schema.")
        sys.exit(1)

    insert_sql = build_insert_sql(actual_cols)
    param_count = insert_sql.count("%s")

    # Per-code summary
    series_in_file = df["series_code"].unique()
    log.info(f"\nSeries in file: {list(series_in_file)}")

    # Check what's already in DB to report skip counts
    existing_keys = get_existing_keys(conn, list(series_in_file))
    log.info(f"Existing rows in DB for these series: {len(existing_keys)}")

    all_rows = []
    new_count = 0
    skip_count = 0

    for _, row in df.iterrows():
        key = (row["series_code"], row["obs_date"].strftime("%Y-%m-%d"))
        if key in existing_keys:
            skip_count += 1
            continue
        try:
            t = build_row_tuple(row, actual_cols)
            if len(t) != param_count:
                log.error(f"Row param count mismatch: expected {param_count}, got {len(t)} for {key}")
                continue
            all_rows.append(t)
            new_count += 1
        except Exception as e:
            log.warning(f"Error building row for {key}: {e} — skipping")

    log.info(f"  {skip_count} rows already in DB (will be skipped by ON CONFLICT)")
    log.info(f"  {new_count} new rows to insert")

    if args.dry_run:
        log.info("[DRY RUN] No data written to DB.")
        # Print sample of what would be inserted
        log.info(f"  Sample row (first): {all_rows[0] if all_rows else 'None'}")
        conn.close()
        return

    if not all_rows:
        log.info("All rows already exist in DB — nothing to insert.")
        conn.close()
        return

    # Batch insert
    inserted = 0
    try:
        with conn.cursor() as cur:
            for i in range(0, len(all_rows), BATCH_SIZE):
                batch = all_rows[i:i+BATCH_SIZE]
                cur.executemany(insert_sql, batch)
                inserted += len(batch)
                log.info(f"  Inserted batch: {inserted}/{len(all_rows)} rows")
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"Insert failed: {e}")
        raise

    log.info(f"\n✓ Done — {inserted} rows inserted across {len(series_in_file)} series")

    # Post-ingest summary per series
    log.info("\nPer-series summary:")
    for code in series_in_file:
        subset = df[df["series_code"] == code]
        log.info(f"  {code:<30} {len(subset)} rows  ({subset['obs_date'].min().date()} → {subset['obs_date'].max().date()})")

    conn.close()


if __name__ == "__main__":
    main()
