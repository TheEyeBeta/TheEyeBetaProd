"""Persist guard violations to Postgres."""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import psycopg
import structlog

from guard_service.validator import Outcome, Violation

log = structlog.get_logger()

_RESOLUTION_MAP = {
    Outcome.RETRY: "retry",
    Outcome.ESCALATE: "escalate",
    Outcome.REJECT: "reject",
}


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


async def count_violations_for_run(run_id: str) -> int:
    """Return how many guard_violation rows already exist for a run."""
    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM theeyebeta.guard_violations WHERE run_id = %s",
            (UUID(run_id),),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def insert_violations(
    *,
    agent_id: str,
    run_id: str,
    violations: list[Violation],
    outcome: Outcome,
) -> None:
    """Insert one row per violation when outcome is not PASS."""
    if not violations or outcome == Outcome.PASS:
        return
    resolution = _RESOLUTION_MAP.get(outcome, "reject")
    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        for violation in violations:
            await conn.execute(
                """
                INSERT INTO theeyebeta.guard_violations
                    (run_id, agent_id, violation_type, severity, detail, resolution)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    UUID(run_id),
                    agent_id,
                    violation.type,
                    violation.severity,
                    json.dumps({"message": violation.detail}),
                    resolution,
                ),
            )
        await conn.commit()
    log.info(
        "guard_violations_inserted",
        agent_id=agent_id,
        run_id=run_id,
        count=len(violations),
        resolution=resolution,
    )


async def load_run_context(run_id: str) -> tuple[dict[str, Any] | None, set[str]]:
    """Load snapshot JSON and universe symbols for a run when not supplied by caller."""
    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        cur = await conn.execute(
            """
            SELECT ar.snapshot_id, dsp.blob_uri
              FROM theeyebeta.agent_runs ar
              LEFT JOIN theeyebeta.data_snapshots_packaged dsp
                ON dsp.snapshot_id = ar.snapshot_id
             WHERE ar.id = %s
            """,
            (UUID(run_id),),
        )
        row = await cur.fetchone()
    if not row or row[0] is None:
        return None, set()
    # Snapshot blob loading is delegated to callers supplying snapshot_json in gRPC.
    return None, set()
