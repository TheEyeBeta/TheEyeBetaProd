"""Run the agent chain-of-command and publish operator briefings."""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import structlog
from dotenv import load_dotenv

from zinc_schemas.agent_hierarchy import OPERATOR_AUDIENCE, load_agent_hierarchy
from zinc_schemas.agent_reports import (
    AgentReportCreate,
    build_report_summary,
    fetch_reports_for_parent,
    insert_agent_report,
)

load_dotenv()

log = structlog.get_logger()

LATEST_SNAPSHOT_SQL = """
SELECT id, market, trade_date
  FROM theeyebeta.data_snapshots_packaged
 WHERE ($1::text IS NULL OR market = $1)
 ORDER BY packaged_at DESC
 LIMIT 1
"""


def _pg_dsn() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def _runtime_url() -> str:
    return os.environ.get("AGENT_RUNTIME_URL", "http://127.0.0.1:8004").rstrip("/")


async def _agent_active(conn: asyncpg.Connection, agent_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM theeyebeta.agents WHERE id = $1 AND active",
        agent_id,
    )
    return row is not None


async def _run_agent(
    client: httpx.AsyncClient,
    *,
    agent_id: str,
    snapshot_id: UUID,
    kind: str,
    parent_run_id: UUID | None,
    subordinate_reports: list[dict[str, Any]],
    operator_context: dict[str, str],
) -> dict[str, Any]:
    """POST to agent-runtime and return the JSON body."""
    payload: dict[str, Any] = {
        "snapshot_id": str(snapshot_id),
        "kind": kind,
        "agent_messages": [],
        "operator_context": operator_context,
        "subordinate_reports": subordinate_reports,
    }
    if parent_run_id is not None:
        payload["parent_run_id"] = str(parent_run_id)
    response = await client.post(
        f"{_runtime_url()}/agents/{agent_id}/run",
        json=payload,
        timeout=180.0,
    )
    response.raise_for_status()
    return response.json()


async def run_reporting_chain(
    *,
    market: str | None,
    dry_run: bool,
    operator_note: str,
) -> dict[str, Any]:
    """Execute bottom-up chain and write operator briefings."""
    hierarchy = load_agent_hierarchy()
    period_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    operator_context = {
        "requested_by": "reporting_chain_worker",
        "note": operator_note or "Scheduled chain-of-command briefing",
    }
    stats: dict[str, Any] = {
        "agents_run": 0,
        "reports_written": 0,
        "skipped": [],
        "errors": [],
    }

    conn = await asyncpg.connect(_pg_dsn())
    try:
        snap = await conn.fetchrow(LATEST_SNAPSHOT_SQL, market)
        if snap is None and not dry_run:
            msg = f"No packaged snapshot found for market={market!r}"
            raise ValueError(msg)

        if dry_run:
            stats["dry_run"] = True
            stats["rollup_order"] = hierarchy.rollup_order()
            stats["snapshot_id"] = str(snap["id"]) if snap else None
            stats["market"] = snap["market"] if snap else market
            return stats

        snapshot_id = snap["id"]
        log.info(
            "reporting_chain_snapshot",
            snapshot_id=str(snapshot_id),
            market=snap["market"],
            trade_date=str(snap["trade_date"]),
        )

        parent_run_ids: dict[str, UUID] = {}
        async with httpx.AsyncClient() as client:
            for agent_id in hierarchy.rollup_order():
                if not await _agent_active(conn, agent_id):
                    stats["skipped"].append(agent_id)
                    log.warning("reporting_chain_agent_inactive", agent_id=agent_id)
                    continue

                children = hierarchy.children_of(agent_id)
                child_reports = await fetch_reports_for_parent(conn, agent_id, since=period_start)
                subordinate_payload = [
                    {
                        "agent_id": row.agent_id,
                        "summary": row.summary,
                        "payload": row.payload,
                    }
                    for row in child_reports
                ]
                kind = "rollup" if children and subordinate_payload else "run"
                parent_run_id = None
                if hierarchy.agents[agent_id].reports_to:
                    parent_run_id = parent_run_ids.get(hierarchy.agents[agent_id].reports_to)

                try:
                    body = await _run_agent(
                        client,
                        agent_id=agent_id,
                        snapshot_id=snapshot_id,
                        kind=kind,
                        parent_run_id=parent_run_id,
                        subordinate_reports=subordinate_payload,
                        operator_context=operator_context,
                    )
                except Exception as exc:  # noqa: BLE001
                    stats["errors"].append({"agent_id": agent_id, "error": str(exc)})
                    log.error("reporting_chain_agent_failed", agent_id=agent_id, error=str(exc))
                    continue

                stats["agents_run"] += 1
                run_id = UUID(body["run_id"])
                parent_run_ids[agent_id] = run_id
                audience = hierarchy.audience_for(agent_id)
                report_type = "rollup" if kind == "rollup" else "briefing"
                if agent_id == "master-orchestrator":
                    report_type = "trade_synthesis"

                await insert_agent_report(
                    conn,
                    AgentReportCreate(
                        agent_id=agent_id,
                        audience=audience,
                        run_id=run_id,
                        report_type=report_type,
                        period_start=period_start,
                        period_end=datetime.now(tz=UTC),
                        summary=build_report_summary(body),
                        payload=body,
                    ),
                )
                stats["reports_written"] += 1
                log.info(
                    "reporting_chain_report_published",
                    agent_id=agent_id,
                    audience=audience,
                    report_type=report_type,
                )

        operator_count = await conn.fetchval(
            """
            SELECT COUNT(*)::int FROM theeyebeta.agent_reports
             WHERE audience = $1 AND created_at >= $2
            """,
            OPERATOR_AUDIENCE,
            period_start,
        )
        stats["operator_briefings_today"] = operator_count
        return stats
    finally:
        await conn.close()


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Run agent chain-of-command reporting")
    parser.add_argument("--market", default="US", help="Market filter for latest snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without LLM calls")
    parser.add_argument(
        "--operator-note",
        default="",
        help="Optional note injected as operator_context for all agents",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_reporting_chain(
            market=args.market or None,
            dry_run=args.dry_run,
            operator_note=args.operator_note,
        ),
    )
    log.info("reporting_chain_complete", **result)


if __name__ == "__main__":
    main()
