#!/usr/bin/env python3
"""List repo migrations vs database alembic_version stamps (read-only).

Requires SELECT on alembic_version tables (postgres on server; tb_app may lack access).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

PROD_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOT = PROD_ROOT.parent / "TheEyeBetaLocal"

_raw = os.environ.get("DATABASE_URL", "")
DATABASE_URL = re.sub(r"\+\w+", "", _raw, count=1)


def _repo_alembic_versions() -> list[str]:
    versions_dir = PROD_ROOT / "db" / "migrations" / "versions"
    return sorted(p.stem for p in versions_dir.glob("*.py") if p.name != "__init__.py")


def _repo_theeyebeta_sql() -> list[str]:
    d = PROD_ROOT / "db" / "migrations" / "theeyebeta_versions"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.sql"))


def _repo_local_sql() -> list[str]:
    d = LOCAL_ROOT / "db" / "schema" / "migrations"
    return sorted(p.name for p in d.glob("*.sql"))


def main() -> None:
    """Print pending migrations by track."""
    print("=== REPO MIGRATION INVENTORY ===\n")

    alembic = _repo_alembic_versions()
    print(f"Prod Alembic (theeyebeta schema via db/migrations/versions): {len(alembic)} files")
    for v in alembic:
        print(f"  - {v}")

    te_sql = _repo_theeyebeta_sql()
    print(f"\nProd theeyebeta_versions SQL: {len(te_sql)} files")
    for v in te_sql:
        print(f"  - {v}")

    local_sql = _repo_local_sql()
    print(f"\nLocal public schema SQL (db/schema/migrations): {len(local_sql)} files")
    for v in local_sql:
        print(f"  - {v}")

    if not DATABASE_URL:
        print("\nDATABASE_URL not set — cannot compare to live DB")
        sys.exit(0)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            pub = conn.execute(
                "SELECT version_num FROM public.alembic_version LIMIT 1",
            ).fetchone()
            beta = conn.execute(
                "SELECT version_num FROM theeyebeta.alembic_version LIMIT 1",
            ).fetchone()
    except psycopg.Error as exc:
        print(f"\nCannot read alembic_version ({exc})")
        print("Run on server as postgres to get PENDING list.")
        sys.exit(2)

    pub_head = pub[0] if pub else None
    beta_head = beta[0] if beta else None
    print(f"\n=== LIVE DB HEADS ===")
    print(f"public.alembic_version:     {pub_head}")
    print(f"theeyebeta.alembic_version: {beta_head}")

    if pub_head and pub_head in [v.split("_")[0] for v in local_sql]:
        pass

    pending_alembic = [v for v in alembic if pub_head and v > str(pub_head)]
    # simpler: index-based
    if beta_head and beta_head in alembic:
        idx = alembic.index(beta_head)
        pending_beta = alembic[idx + 1 :]
    else:
        pending_beta = alembic

    if pub_head:
        local_pending = [f for f in local_sql if f > str(pub_head)]
    else:
        local_pending = local_sql

    te_pending = [v for v in te_sql if beta_head and v > str(beta_head)] if beta_head else te_sql

    print("\n=== LIKELY PENDING (verify on server) ===")
    print("theeyebeta Alembic after head:")
    for v in pending_beta:
        print(f"  PENDING  {v}")
    print("theeyebeta_versions SQL after head:")
    for v in te_pending:
        print(f"  PENDING? {v}")
    print("Local public SQL after public head:")
    for v in local_pending[-5:]:
        print(f"  PENDING? {v}")
    if any("028_trask" in f for f in local_pending):
        print("  PENDING  028_trask_new_workers.sql (Trask Prod workers)")


if __name__ == "__main__":
    main()
