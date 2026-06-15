#!/usr/bin/env python3
"""List Prod Alembic migrations vs ``theeyebeta.alembic_version`` (read-only)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

PROD_ROOT = Path(__file__).resolve().parents[1]

_raw = os.environ.get("DATABASE_URL", "")
DATABASE_URL = re.sub(r"\+\w+", "", _raw, count=1)


def _repo_alembic_versions() -> list[str]:
    versions_dir = PROD_ROOT / "db" / "migrations" / "versions"
    return sorted(p.stem for p in versions_dir.glob("*.py") if p.name != "__init__.py")


def main() -> None:
    """Print pending Prod Alembic migrations after the live theeyebeta head."""
    alembic = _repo_alembic_versions()
    print("=== PROD ALEMBIC (theeyebeta schema) ===\n")
    for version in alembic:
        print(f"  - {version}")

    if not DATABASE_URL:
        print("\nDATABASE_URL not set — cannot compare to live DB")
        sys.exit(0)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            row = conn.execute(
                "SELECT version_num FROM theeyebeta.alembic_version LIMIT 1",
            ).fetchone()
    except psycopg.Error as exc:
        print(f"\nCannot read theeyebeta.alembic_version ({exc})")
        sys.exit(2)

    head = row[0] if row else None
    print(f"\n=== LIVE HEAD ===\ntheeyebeta.alembic_version: {head or '(none)'}")

    pending = alembic[alembic.index(head) + 1 :] if head and head in alembic else alembic

    print("\n=== PENDING ===")
    if pending:
        for version in pending:
            print(f"  PENDING  {version}")
        sys.exit(1)
    print("  (none — at head)")
    sys.exit(0)


if __name__ == "__main__":
    main()
