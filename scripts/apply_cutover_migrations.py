#!/usr/bin/env python3
"""Apply Prod cutover migrations 0019-0024 when Alembic head is out of sync.

Use when ``theeyebeta.alembic_version`` holds a Local-track revision
(e.g. ``0013_prices_intraday``) that is not in the central Alembic chain.
Idempotent: skips steps when target tables already exist.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import re
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "db" / "migrations" / "versions"

MIGRATION_FILES = [
    "0019_trading_calendar.py",
    "0020_worker_ops.py",
    "0021_pipeline_alerts.py",
    "0022_ind_technical_daily.py",
    "0023_sector_daily.py",
    "0024_public_ticker_map.py",
]

TARGET_HEAD = "0024_public_ticker_map"


def _load_sql(path: Path) -> str:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        msg = f"Cannot load {path}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.SQL_UP)


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
              FROM information_schema.tables
             WHERE table_schema = 'theeyebeta'
               AND table_name = $1
            """,
            table,
        ),
    )


async def apply(dry_run: bool) -> None:
    """Run cutover SQL and stamp Alembic head."""
    raw = os.environ.get("DATABASE_URL", "")
    dsn = re.sub(r"\+\w+", "", raw, count=1)
    if not dsn:
        msg = "DATABASE_URL is not set"
        raise RuntimeError(msg)

    conn = await asyncpg.connect(dsn)
    try:
        current = await conn.fetchval("SELECT version_num FROM theeyebeta.alembic_version")
        print(f"current alembic_version: {current}")

        for filename in MIGRATION_FILES:
            path = VERSIONS / filename
            sql = _load_sql(path)
            marker_table = {
                "0019": "trading_calendar",
                "0020": "worker_runs",
                "0021": "audit_data_gaps",
                "0022": "ind_technical_daily",
                "0023": "sector_daily",
                "0024": "public_ticker_map",
            }[filename[:4]]
            if await _table_exists(conn, marker_table):
                print(f"skip {filename} ({marker_table} exists)")
                continue
            print(f"apply {filename}")
            if dry_run:
                continue
            await conn.execute(sql)

        if not dry_run:
            await conn.execute("DELETE FROM theeyebeta.alembic_version")
            await conn.execute(
                """
                INSERT INTO theeyebeta.alembic_version (version_num)
                VALUES ($1)
                """,
                TARGET_HEAD,
            )
            final = await conn.fetchval("SELECT version_num FROM theeyebeta.alembic_version")
            print(f"stamped alembic_version: {final}")
    finally:
        await conn.close()


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Apply cutover migrations 0019-0024")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(apply(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
