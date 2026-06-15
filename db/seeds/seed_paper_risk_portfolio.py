"""Seed a paper trading account + portfolio with industry-standard risk mandate.

Idempotent — safe to re-run. Does not create positions (empty book until paper
trades flow through OMS).

Usage:
    uv run python db/seeds/seed_paper_risk_portfolio.py

Portfolio UUID is fixed so .env can reference DEFAULT_PORTFOLIO_ID.
"""

from __future__ import annotations

import os
import sys

import psycopg
import structlog
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()

PAPER_ACCOUNT_ID = "b10e8400-e29b-41d4-a716-446655440001"
PAPER_PORTFOLIO_ID = "b20e8400-e29b-41d4-a716-446655440002"

# Industry-standard starter limits (tweak via portfolios.mandate later).
STANDARD_MANDATE = {
    "max_position_pct": 0.10,
    "max_sector_pct": 0.35,
    "max_correlation_cluster_pct": 0.40,
    "max_var": 0.03,
    "max_drawdown_pct": 0.15,
    "max_hhi": 0.30,
}


def _dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def main() -> None:
    """Upsert paper account and portfolio with standard mandate."""
    import json

    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO theeyebeta.accounts (id, external_id, broker, mode, metadata)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (external_id) DO UPDATE SET
                    mode = EXCLUDED.mode,
                    metadata = EXCLUDED.metadata
                """,
                (
                    PAPER_ACCOUNT_ID,
                    "theeyebeta-paper",
                    "alpaca",
                    "paper",
                    json.dumps({"purpose": "default paper book for risk metrics"}),
                ),
            )
            cur.execute(
                """
                INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    mandate = EXCLUDED.mandate,
                    name = EXCLUDED.name
                """,
                (
                    PAPER_PORTFOLIO_ID,
                    PAPER_ACCOUNT_ID,
                    "paper-standard",
                    json.dumps(STANDARD_MANDATE),
                ),
            )
        conn.commit()

    log.info(
        "paper_risk_portfolio_seeded",
        account_id=PAPER_ACCOUNT_ID,
        portfolio_id=PAPER_PORTFOLIO_ID,
        mandate=STANDARD_MANDATE,
    )
    print(f"DEFAULT_PORTFOLIO_ID={PAPER_PORTFOLIO_ID}")


if __name__ == "__main__":
    main()
