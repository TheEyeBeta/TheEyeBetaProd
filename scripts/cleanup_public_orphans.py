"""Remove schema-leak artefacts from the public schema.

Moves alembic_version metadata into theeyebeta, drops orphaned data tables
from public, and sets role-level search_path so future sessions always land
in theeyebeta first.

Usage:
    uv run python scripts/cleanup_public_orphans.py
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import psycopg
import psycopg.errors
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL: str = re.sub(r"\+\w+", "", _raw_url, count=1)

# Tables that are expected / allowed as public orphans.
_ALLOWED_ORPHANS: set[str] = {
    "alembic_version",
    "exchanges",
    "corporate_actions",
    "signals",
}
# Data tables only (Gate A — must be empty before we can safely drop).
_DATA_ORPHANS: list[str] = ["exchanges", "corporate_actions", "signals"]

_DB_NAME = "TheEyeBeta2025Live"


def _p(msg: str = "") -> None:
    """Print *msg* with immediate flush."""
    print(msg, flush=True)


def _conn(autocommit: bool = True) -> psycopg.Connection[Any]:
    """Open a psycopg3 connection to DATABASE_URL."""
    if not DATABASE_URL:
        _p("ERROR: DATABASE_URL is not set.")
        sys.exit(1)
    return psycopg.connect(DATABASE_URL, autocommit=autocommit)


# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC BLOCK
# ─────────────────────────────────────────────────────────────────────────────


def run_diagnostics(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Collect and print diagnostic information.

    Returns a dict of findings for use by the gate checks.
    """
    _p("─── DIAGNOSTICS ───────────────────────────────────────────────")

    findings: dict[str, Any] = {
        "public_orphans": {},  # table_name → row_count (None for alembic_version)
        "av_public": None,  # version_num from public.alembic_version
        "av_theeyebeta": None,  # version_num from theeyebeta.alembic_version
        "extra_leaks": [],  # theeyebeta-named tables in public outside allowed set
        "public_hypertables": [],  # hypertable names in schema public
    }

    # Which of the known candidates exist in public?
    for table in ["alembic_version", "exchanges", "corporate_actions", "signals"]:
        row = conn.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema='public' AND table_name=%s
            """,
            (table,),
        ).fetchone()
        if row is not None:
            if table != "alembic_version":
                # Use pg_class.reltuples for a fast estimate; avoids full seq-scan
                # on potentially huge tables (e.g. signals with 100M+ rows).
                cnt_row = conn.execute(
                    """
                    SELECT reltuples::bigint
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = %s
                    """,
                    (table,),
                ).fetchone()
                est = int(cnt_row[0]) if cnt_row else -1
                findings["public_orphans"][table] = est
                _p(f"  public.{table} exists  (est. rows: {est})")
            else:
                findings["public_orphans"][table] = None
                _p(f"  public.{table} exists  (metadata table — row count not checked)")
        else:
            _p(f"  public.{table} does NOT exist")

    # alembic_version values
    if "alembic_version" in findings["public_orphans"]:
        row = conn.execute("SELECT version_num FROM public.alembic_version").fetchone()
        findings["av_public"] = row[0] if row else None
    try:
        row = conn.execute("SELECT version_num FROM theeyebeta.alembic_version").fetchone()
        findings["av_theeyebeta"] = row[0] if row else None
    except Exception as exc:
        findings["av_theeyebeta"] = f"ERROR: {exc}"
    _p(f"  public.alembic_version.version_num:      {findings['av_public']}")
    _p(f"  theeyebeta.alembic_version.version_num:  {findings['av_theeyebeta']}")

    # Any other theeyebeta-named tables in public (outside the allowed set)
    rows = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
          AND table_name IN (
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'theeyebeta' AND table_type = 'BASE TABLE'
          )
        ORDER BY table_name
        """).fetchall()
    all_public_leaks = {r[0] for r in rows}
    findings["extra_leaks"] = sorted(all_public_leaks - _ALLOWED_ORPHANS)
    if findings["extra_leaks"]:
        _p(f"  !! Unexpected public leaks: {findings['extra_leaks']}")
    else:
        _p("  No unexpected public leaks beyond the known set.")

    # Hypertables in schema public
    ht_rows = conn.execute("""
        SELECT hypertable_name
        FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'public'
        ORDER BY hypertable_name
        """).fetchall()
    findings["public_hypertables"] = [r[0] for r in ht_rows]
    if findings["public_hypertables"]:
        _p(f"  !! Hypertables in public: {findings['public_hypertables']}")
    else:
        _p("  No hypertables in schema public.")

    _p()
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# SAFETY GATES
# ─────────────────────────────────────────────────────────────────────────────


def check_gates(findings: dict[str, Any]) -> None:
    """Evaluate all safety gates.

    Prints ABORT and exits with code 2 if any gate fails.
    Nothing in the database is touched before this returns.
    """
    _p("─── SAFETY GATES ───────────────────────────────────────────────")

    # GATE A — every data orphan in public must be empty
    for table in _DATA_ORPHANS:
        if table not in findings["public_orphans"]:
            continue  # table doesn't exist in public; nothing to protect
        cnt = findings["public_orphans"][table]
        if cnt != 0:
            _p(f"  GATE A: ✗  public.{table} has {cnt} row(s) — cannot safely drop.")
            _p(f"ABORT: GATE A failed — public.{table} is not empty ({cnt} rows)")
            sys.exit(2)
    _p("  GATE A: ✓  all public data orphans are empty")

    # GATE B — theeyebeta.alembic_version must be at 0009_audit
    if findings["av_theeyebeta"] != "0009_audit":
        _p(f"  GATE B: ✗  theeyebeta.alembic_version = {findings['av_theeyebeta']!r}")
        _p(f"ABORT: GATE B failed — expected '0009_audit', got {findings['av_theeyebeta']!r}")
        sys.exit(2)
    _p("  GATE B: ✓  theeyebeta.alembic_version = '0009_audit'")

    # GATE C — no hypertables in public
    if findings["public_hypertables"]:
        _p(f"  GATE C: ✗  hypertables in public: {findings['public_hypertables']}")
        _p(
            f"ABORT: GATE C failed — hypertables found in schema public: "
            f"{findings['public_hypertables']}"
        )
        sys.exit(2)
    _p("  GATE C: ✓  no hypertables in schema public")

    # GATE D — no unexpected leaks beyond the allowed set
    if findings["extra_leaks"]:
        _p(f"  GATE D: ✗  unexpected leaks: {findings['extra_leaks']}")
        _p(
            f"ABORT: GATE D failed — unexpected theeyebeta tables found in public: "
            f"{findings['extra_leaks']}"
        )
        sys.exit(2)
    _p("  GATE D: ✓  no unexpected table leaks in schema public")

    _p()


# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP TRANSACTION
# ─────────────────────────────────────────────────────────────────────────────


def run_cleanup(findings: dict[str, Any]) -> dict[str, Any]:
    """Execute the cleanup inside a single transaction.

    Returns a summary dict. Calls sys.exit(2) on any failure after rollback.
    """
    _p("─── CLEANUP TRANSACTION ────────────────────────────────────────")

    summary: dict[str, Any] = {
        "av_rows_moved": 0,
        "tables_dropped": [],
    }

    with _conn(autocommit=False) as conn:
        try:
            # Step 1: migrate alembic_version metadata (if public table exists)
            if "alembic_version" in findings["public_orphans"]:
                cur = conn.execute("""
                    INSERT INTO theeyebeta.alembic_version (version_num)
                      SELECT version_num FROM public.alembic_version
                      ON CONFLICT (version_num) DO NOTHING
                    """)
                summary["av_rows_moved"] = cur.rowcount

            # Step 2: sanity check — exactly 1 row for 0009_audit
            row = conn.execute("""
                SELECT count(*) FROM theeyebeta.alembic_version
                WHERE version_num = '0009_audit'
                """).fetchone()
            if row is None or int(row[0]) != 1:
                conn.rollback()
                _p(
                    f"  ✗ Sanity check failed: "
                    f"count(version_num='0009_audit') = {row[0] if row else 'NULL'}"
                )
                _p(
                    "ABORT: transaction rolled back — "
                    "theeyebeta.alembic_version sanity check failed"
                )
                sys.exit(2)
            _p("  ✓ Sanity check: theeyebeta.alembic_version has exactly 1 × '0009_audit'")

            # Step 3: drop orphan tables in dependency-safe order
            for table in [
                "public.signals",
                "public.corporate_actions",
                "public.exchanges",
                "public.alembic_version",
            ]:
                tbl_short = table.split(".")[1]
                exists = tbl_short in findings["public_orphans"]
                if exists:
                    conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                    summary["tables_dropped"].append(table)
                    _p(f"  ✓ Dropped {table}")
                else:
                    _p(f"  – Skipped {table} (did not exist)")

            conn.commit()
            _p("  ✓ Transaction committed.")

        except Exception:
            conn.rollback()
            raise

    _p()
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# ROLE search_path
# ─────────────────────────────────────────────────────────────────────────────


def set_role_search_paths() -> list[str]:
    """Set role-level search_path for the three key roles (idempotent).

    Runs outside any transaction (each ALTER ROLE auto-commits in PG DDL).
    Returns the list of roles successfully updated.
    """
    _p("─── ROLE SEARCH_PATH ───────────────────────────────────────────")

    roles = ["postgres", "tb_app", "tb_rnd_readonly"]
    updated: list[str] = []

    with _conn(autocommit=True) as conn:
        for role in roles:
            try:
                conn.execute(
                    f'ALTER ROLE {role} IN DATABASE "{_DB_NAME}" '
                    f"SET search_path TO theeyebeta, public"
                )
                _p(f"  ✓ ALTER ROLE {role} — search_path set")
                updated.append(role)
            except psycopg.errors.UndefinedObject:
                _p(f"  – Role '{role}' not found — skipped")
            except Exception as exc:
                _p(f"  ✗ Role '{role}' failed: {exc}")

    _p()
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """Orchestrate diagnostics → gates → cleanup → role update."""
    _p("═" * 65)
    _p("  theeyebeta — Public Schema Orphan Cleanup")
    _p("═" * 65)
    _p()

    with _conn(autocommit=True) as diag_conn:
        findings = run_diagnostics(diag_conn)

    check_gates(findings)

    summary = run_cleanup(findings)

    roles_updated = set_role_search_paths()

    # ── Final summary ─────────────────────────────────────────────────────────
    _p("─── SUMMARY ────────────────────────────────────────────────────")
    av_note = (
        f"{summary['av_rows_moved']} row(s) inserted "
        "(conflict-free; 0 means already present in theeyebeta)"
    )
    _p(f"  alembic_version migrated: {av_note}")
    if summary["tables_dropped"]:
        for t in summary["tables_dropped"]:
            _p(f"  dropped: {t}")
    else:
        _p("  no tables dropped (none existed)")
    _p(f"  roles updated:   {sorted(roles_updated)}")
    _p("═" * 65)


if __name__ == "__main__":
    main()
