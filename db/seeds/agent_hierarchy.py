"""Apply chain-of-command from config/agents/hierarchy.yaml to theeyebeta.agents.

Usage:
    uv run python db/seeds/agent_hierarchy.py

Idempotent: upserts lead agents and updates ``reports_to`` for all hierarchy nodes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import structlog
from dotenv import load_dotenv

from zinc_schemas.agent_hierarchy import load_agent_hierarchy

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

log = structlog.get_logger()


def _build_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        log.error("DATABASE_URL not set")
        sys.exit(1)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def main() -> None:
    """Upsert lead agents and wire reports_to edges."""
    hierarchy = load_agent_hierarchy()
    dsn = _build_dsn()
    upserted = 0
    linked = 0

    with psycopg.connect(dsn) as conn:
        for agent_id, entry in hierarchy.agents.items():
            if entry.department and entry.constitution_path and entry.model_default:
                conn.execute(
                    """
                    INSERT INTO theeyebeta.agents
                        (id, department, role, model_default, model_fallback,
                         constitution_path, active)
                    VALUES (%s, %s, %s, %s, %s, %s, true)
                    ON CONFLICT (id) DO UPDATE SET
                        department = EXCLUDED.department,
                        role = EXCLUDED.role,
                        model_default = EXCLUDED.model_default,
                        model_fallback = EXCLUDED.model_fallback,
                        constitution_path = EXCLUDED.constitution_path,
                        active = true,
                        updated_at = now()
                    """,
                    (
                        agent_id,
                        entry.department,
                        entry.role or agent_id,
                        entry.model_default,
                        entry.model_fallback,
                        entry.constitution_path,
                    ),
                )
                upserted += 1

            cur = conn.execute(
                """
                UPDATE theeyebeta.agents
                   SET reports_to = %s, updated_at = now()
                 WHERE id = %s
                """,
                (entry.reports_to, agent_id),
            )
            if cur.rowcount:
                linked += 1

        conn.commit()

    print(f"Hierarchy applied: {upserted} lead upserts, {linked} reports_to links")  # noqa: T201


if __name__ == "__main__":
    main()
