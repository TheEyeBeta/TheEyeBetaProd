"""Seed theeyebeta.agents with the technical-analyst agent.

Usage:
    uv run python db/seeds/agents.py

Idempotent: ON CONFLICT (id) DO UPDATE refreshes model and constitution path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import structlog
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

log = structlog.get_logger()


def _build_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def main() -> None:
    """Upsert the technical-analyst agent row."""
    dsn = _build_dsn()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            """
            INSERT INTO theeyebeta.agents
                (id, department, role, model_default, model_fallback,
                 constitution_path, active)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                model_default     = EXCLUDED.model_default,
                constitution_path = EXCLUDED.constitution_path,
                active            = true,
                updated_at        = now()
            """,
            (
                "technical-analyst",
                "markets",
                "Technical analysis on per-market snapshots",
                "gpt-4o-mini",
                None,
                "agents/technical-analyst.md",
                True,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, department, model_default, active FROM theeyebeta.agents"
        ).fetchall()
    print(f"Agents table: {len(row)} row(s)")  # noqa: T201
    for r in row:
        print(f"  {r[0]}  dept={r[1]}  model={r[2]}  active={r[3]}")  # noqa: T201


if __name__ == "__main__":
    main()
