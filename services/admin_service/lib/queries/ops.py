"""Database queries backing ``GET /admin/ops/pulse``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import asyncpg

from lib.worker_registry import DEFAULT_HEARTBEAT_INTERVAL, WORKER_HEARTBEAT_INTERVALS

HEARTBEAT_STALE_MULTIPLIER = 2


async def fetch_open_breakers(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Return open circuit breakers with component context."""
    rows = await conn.fetch(
        """
        SELECT b.id, b.component_id, b.opened_at, b.failure_count,
               COALESCE(b.config->>'failure_threshold', '3') AS failure_threshold,
               c.display_name
          FROM theeyebeta.trask_circuit_breakers b
          LEFT JOIN theeyebeta.trask_components c ON c.component_id = b.component_id
         WHERE b.state = 'open'
         ORDER BY b.opened_at DESC NULLS LAST
        """,
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        reason = f"failure_count={row['failure_count']}"
        result.append(
            {
                "id": str(row["id"]),
                "component": row["component_id"],
                "opened_at": row["opened_at"].isoformat() if row["opened_at"] else None,
                "reason": reason,
            },
        )
    return result


async def fetch_critical_alerts(
    conn: asyncpg.Connection,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return unacknowledged CRITICAL/ESCALATE alerts."""
    rows = await conn.fetch(
        """
        SELECT alert_id, severity, worker_name, title, message, created_at
          FROM theeyebeta.audit_alerts
         WHERE severity IN ('CRITICAL', 'ESCALATE')
           AND acknowledged_at IS NULL
           AND resolved_at IS NULL
         ORDER BY created_at DESC
         LIMIT $1
        """,
        limit,
    )
    return [
        {
            "id": str(row["alert_id"]),
            "severity": row["severity"],
            "source": row["worker_name"] or "system",
            "message": row["message"] or row["title"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]


async def fetch_last_worker_runs(
    conn: asyncpg.Connection,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return recent worker runs."""
    rows = await conn.fetch(
        """
        SELECT worker_name, status, started_at, ended_at, records_written
          FROM theeyebeta.worker_runs
         ORDER BY started_at DESC
         LIMIT $1
        """,
        limit,
    )
    return [
        {
            "worker": row["worker_name"],
            "status": row["status"],
            "started_at": row["started_at"].isoformat(),
            "ended_at": row["ended_at"].isoformat() if row["ended_at"] else None,
            "records_written": row["records_written"] or 0,
        }
        for row in rows
    ]


async def fetch_stale_heartbeats(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Return workers whose heartbeat exceeds expected interval."""
    rows = await conn.fetch(
        """
        SELECT worker_id, last_heartbeat, metadata
          FROM theeyebeta.worker_heartbeats
         ORDER BY worker_id
        """,
    )
    now = datetime.now(tz=UTC)
    stale: list[dict[str, Any]] = []
    for row in rows:
        worker_id = row["worker_id"]
        expected = WORKER_HEARTBEAT_INTERVALS.get(worker_id, DEFAULT_HEARTBEAT_INTERVAL)
        last_hb = row["last_heartbeat"]
        if last_hb is None:
            stale.append(
                {
                    "worker": worker_id,
                    "last_heartbeat": None,
                    "expected_interval_seconds": expected,
                },
            )
            continue
        if last_hb.tzinfo is None:
            last_hb = last_hb.replace(tzinfo=UTC)
        age = (now - last_hb).total_seconds()
        if age > expected * HEARTBEAT_STALE_MULTIPLIER:
            stale.append(
                {
                    "worker": worker_id,
                    "last_heartbeat": last_hb.isoformat(),
                    "expected_interval_seconds": expected,
                },
            )
    return stale


async def fetch_pipeline_freshness(conn: asyncpg.Connection) -> dict[str, str | None]:
    """Return last successful ingest/compute timestamps."""
    eod = await conn.fetchval(
        """
        SELECT MAX(ended_at)
          FROM theeyebeta.worker_runs
         WHERE worker_name = 'MassiveDailyIngestionWorker'
           AND status = 'COMPLETED'
        """,
    )
    intraday = await conn.fetchval(
        """
        SELECT MAX(ended_at)
          FROM theeyebeta.worker_runs
         WHERE worker_name = 'IntradayIngestionWorker'
           AND status = 'COMPLETED'
        """,
    )
    indicators = await conn.fetchval(
        """
        SELECT MAX(ended_at)
          FROM theeyebeta.worker_runs
         WHERE worker_name IN ('IndicatorComputeWorker', 'TheeyebetaIndicatorWorker')
           AND status = 'COMPLETED'
        """,
    )

    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()

    return {
        "last_eod_ingest": _iso(eod),
        "last_intraday_ingest": _iso(intraday),
        "last_indicators": _iso(indicators),
    }


async def fetch_pending_orders_count(conn: asyncpg.Connection) -> int:
    """Count orders awaiting human approval."""
    count = await conn.fetchval(
        """
        SELECT COUNT(*)::int FROM theeyebeta.orders WHERE status = 'pending_approval'
        """,
    )
    return int(count or 0)


async def fetch_llm_cost_mtd(conn: asyncpg.Connection) -> float:
    """Sum LLM/API costs for the current calendar month."""
    start = datetime.now(tz=UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_date = start.date()
    model_cost = await conn.fetchval(
        """
        SELECT COALESCE(SUM(cost_usd), 0)
          FROM theeyebeta.model_runs
         WHERE created_at >= $1
        """,
        start,
    )
    api_cost = await conn.fetchval(
        """
        SELECT COALESCE(SUM(cost_usd), 0)
          FROM theeyebeta.api_costs
         WHERE ts >= $1::date
        """,
        start_date,
    )
    return float(model_cost or 0) + float(api_cost or 0)


async def fetch_prelive_last_result(conn: asyncpg.Connection) -> dict[str, Any]:
    """Return the most recent cached prelive check summary."""
    row = await conn.fetchrow(
        """
        SELECT run_at, overall, checks
          FROM theeyebeta.prelive_check_cache
         ORDER BY run_at DESC
         LIMIT 1
        """,
    )
    if row is None:
        return {
            "passed": False,
            "run_at": None,
            "checks_passed": 0,
            "checks_failed": 0,
        }
    checks = row["checks"]
    if isinstance(checks, str):
        import json

        checks = json.loads(checks)
    passed = sum(1 for c in checks if c.get("status") == "pass")
    failed = sum(1 for c in checks if c.get("status") == "fail")
    return {
        "passed": row["overall"] == "pass",
        "run_at": row["run_at"].isoformat() if row["run_at"] else None,
        "checks_passed": passed,
        "checks_failed": failed,
    }


async def fetch_audit_chain_status(conn: asyncpg.Connection) -> dict[str, object]:
    """Return latest audit chain verification row."""
    try:
        row = await conn.fetchrow(
            """
            SELECT verified_at, valid, entries_checked, error_message
              FROM theeyebeta.audit_chain_status
             ORDER BY verified_at DESC
             LIMIT 1
            """,
        )
    except asyncpg.UndefinedTableError:
        return {
            "last_verified_at": None,
            "valid": None,
            "entries_checked": 0,
            "error_message": None,
        }
    if row is None:
        return {
            "last_verified_at": None,
            "valid": None,
            "entries_checked": 0,
            "error_message": None,
        }
    verified = row["verified_at"]
    return {
        "last_verified_at": verified,
        "valid": row["valid"],
        "entries_checked": int(row["entries_checked"] or 0),
        "error_message": row["error_message"],
    }


def compute_health(
    *,
    open_breakers: list[dict[str, Any]],
    critical_alerts: list[dict[str, Any]],
    stale_heartbeats: list[dict[str, Any]],
    prelive_passed: bool | None = None,
    audit_chain_valid: bool | None = None,
) -> str:
    """Derive aggregate health from ops signals."""
    if open_breakers or critical_alerts:
        return "critical"
    if prelive_passed is False or audit_chain_valid is False:
        return "degraded"
    if stale_heartbeats:
        return "degraded"
    return "ok"
