"""Seed theeyebeta.instruments from db/seeds/universe.yaml.

Usage:
    uv run python db/seeds/seed_instruments.py

Reads DATABASE_URL from the environment (via .env).  Upserts each entry
using ON CONFLICT (symbol, exchange_id) DO UPDATE so the script is
safe to re-run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import structlog
import yaml
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()

_YAML_PATH = Path(__file__).parent / "universe.yaml"


def _build_dsn() -> str:
    """Return a psycopg-native DSN from DATABASE_URL.

    Strips any SQLAlchemy driver prefix (e.g. ``+asyncpg``, ``+psycopg``).
    """
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    # Remove +driver suffix: postgresql+asyncpg://... → postgresql://...
    if "+asyncpg" in raw:
        raw = raw.replace("+asyncpg", "")
    elif "+psycopg" in raw:
        raw = raw.replace("+psycopg", "")
    return raw


def main() -> None:
    """Load universe.yaml and upsert all instruments into theeyebeta.instruments."""
    entries: list[dict[str, str]] = yaml.safe_load(_YAML_PATH.read_text())
    if not entries:
        log.error("universe.yaml is empty")
        sys.exit(1)

    dsn = _build_dsn()
    seeded = 0

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            for entry in entries:
                symbol: str = entry["symbol"]
                exchange_code: str = entry["exchange"]
                asset_class: str = entry["asset_class"]
                sector: str = entry.get("sector", "")
                industry: str = entry.get("industry", "")

                cur.execute(
                    """
                    INSERT INTO theeyebeta.instruments
                        (symbol, exchange_id, asset_class, sector, industry, active)
                    SELECT
                        %(symbol)s,
                        e.id,
                        %(asset_class)s,
                        %(sector)s,
                        %(industry)s,
                        true
                    FROM theeyebeta.exchanges e
                    WHERE e.code = %(exchange_code)s
                    ON CONFLICT (symbol, exchange_id) DO UPDATE SET
                        sector    = excluded.sector,
                        industry  = excluded.industry,
                        active    = true
                    """,
                    {
                        "symbol": symbol,
                        "exchange_code": exchange_code,
                        "asset_class": asset_class,
                        "sector": sector,
                        "industry": industry,
                    },
                )
                if cur.rowcount:
                    seeded += cur.rowcount
                    log.debug("upserted", symbol=symbol, exchange=exchange_code)
                else:
                    log.warning(
                        "exchange_not_found_skipped",
                        symbol=symbol,
                        exchange=exchange_code,
                    )

        conn.commit()

    print(f"Seeded {seeded} instruments")  # noqa: T201 — intentional user-facing output


if __name__ == "__main__":
    main()
