"""Database access for rnd-agent (tb_rnd_readonly role)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import frontmatter
import psycopg
import structlog

from rnd_agent.models import ProposalDraft, RndAgentOutput

log = structlog.get_logger()

AGENT_ID = "rnd-agent"


async def create_agent_run(dsn: str, *, triggered_by: str = "scheduler") -> UUID:
    """Open an ``agent_runs`` row in ``running`` status."""
    run_id = uuid4()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.agent_runs (id, agent_id, triggered_by, status)
            VALUES (%s, %s, %s, 'running')
            """,
            (run_id, AGENT_ID, triggered_by),
        )
        await conn.commit()
    return run_id


async def finish_agent_run(
    dsn: str,
    run_id: UUID,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Mark an agent run complete."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            UPDATE theeyebeta.agent_runs
               SET status = %s, ended_at = %s, error = %s
             WHERE id = %s
            """,
            (status, datetime.now(tz=UTC), error, run_id),
        )
        await conn.commit()


async def gather_research_inputs(dsn: str, repo_root: Path) -> dict[str, Any]:
    """Collect slow-loop context for the nightly R&D prompt."""
    since_90d = datetime.now(tz=UTC) - timedelta(days=90)
    since_12mo = datetime.now(tz=UTC) - timedelta(days=365)

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        decisions = await _fetch_all(
            conn,
            """
            SELECT d.id, d.run_id, d.instrument_id, d.market, d.decision,
                   d.confidence, d.rationale, d.created_at
              FROM theeyebeta.agent_decisions d
             WHERE d.created_at >= %s
             ORDER BY d.created_at DESC
             LIMIT 500
            """,
            (since_90d,),
        )
        runs = await _fetch_all(
            conn,
            """
            SELECT r.id, r.agent_id, r.triggered_by, r.status, r.started_at, r.ended_at,
                   r.total_cost_usd
              FROM theeyebeta.agent_runs r
             WHERE r.started_at >= %s
             ORDER BY r.started_at DESC
             LIMIT 200
            """,
            (since_90d,),
        )
        audit_summary = await _fetch_all(
            conn,
            """
            SELECT id, ts, actor, action, entity_type, entity_id_safe, payload_summary
              FROM theeyebeta.system_audit_summary
             WHERE ts >= %s
             ORDER BY ts DESC
             LIMIT 200
            """,
            (since_90d,),
        )
        backtest_runs = await _fetch_all(
            conn,
            """
            SELECT id, strategy_id, start_date, end_date, universe, status,
                   started_at, ended_at, result_blob_uri
              FROM theeyebeta.backtest_runs
             WHERE started_at >= %s
             ORDER BY started_at DESC
            """,
            (since_12mo,),
        )
        backtest_ids = [row["id"] for row in backtest_runs]
        backtest_results: list[dict[str, Any]] = []
        if backtest_ids:
            backtest_results = await _fetch_all(
                conn,
                """
                SELECT backtest_id, metric, value
                  FROM theeyebeta.backtest_results
                 WHERE backtest_id = ANY(%s::uuid[])
                """,
                (backtest_ids,),
            )
        agent_registry = await _fetch_all(
            conn,
            "SELECT * FROM system.agent_constitutions ORDER BY agent_id",
        )

    constitutions = _load_constitution_bodies(repo_root, agent_registry)
    pending = await fetch_pending_proposals(dsn)

    return {
        "gathered_at": datetime.now(tz=UTC).isoformat(),
        "agent_decisions_90d": decisions,
        "agent_runs_90d": runs,
        "system_audit_summary_90d": audit_summary,
        "backtest_runs_12mo": backtest_runs,
        "backtest_results_12mo": backtest_results,
        "agent_constitutions": constitutions,
        "pending_proposals": pending,
    }


def _load_constitution_bodies(
    repo_root: Path,
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach constitution markdown bodies from repo paths."""
    rows: list[dict[str, Any]] = []
    for entry in registry:
        rel = str(entry.get("constitution_path") or "")
        path = repo_root / rel if rel else None
        body = ""
        if path and path.is_file():
            doc = frontmatter.load(path)
            body = doc.content.strip()
        rows.append({**entry, "constitution_body": body})
    extra_paths = sorted(
        p
        for pattern in ("*.md", "*.agent.md")
        for p in (repo_root / "agents").rglob(pattern)
        if not p.name.startswith("_")
    )
    known = {str(r.get("constitution_path")) for r in registry}
    for path in extra_paths:
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if rel in known:
            continue
        doc = frontmatter.load(path)
        rows.append(
            {
                "agent_id": doc.get("agent_id") or path.stem,
                "constitution_path": rel,
                "constitution_body": doc.content.strip(),
            },
        )
    return rows


async def fetch_pending_proposals(dsn: str) -> list[dict[str, Any]]:
    """Return pending proposals for digest and de-duplication."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        return await _fetch_all(
            conn,
            """
            SELECT id, category, target, status, rationale, created_at
              FROM theeyebeta.proposals
             WHERE status = 'pending'
             ORDER BY created_at DESC
            """,
        )


async def insert_proposals(
    dsn: str,
    *,
    run_id: UUID,
    proposals: list[ProposalDraft],
) -> list[UUID]:
    """Insert validated proposals and return their IDs."""
    ids: list[UUID] = []
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        for proposal in proposals[:3]:
            proposal_id = uuid4()
            evidence = proposal.evidence
            if hasattr(evidence, "model_dump"):
                evidence_payload = evidence.model_dump()
            else:
                evidence_payload = evidence
            impact_payload = (
                proposal.estimated_impact.model_dump()
                if proposal.estimated_impact is not None
                else None
            )
            await conn.execute(
                """
                INSERT INTO theeyebeta.proposals (
                    id, proposed_by, run_id, category, target,
                    current_value, proposed_value, rationale, evidence,
                    estimated_impact, validation_backtest_id, status
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s, %s::jsonb,
                    %s::jsonb, %s, 'pending'
                )
                """,
                (
                    proposal_id,
                    AGENT_ID,
                    run_id,
                    proposal.category,
                    proposal.target,
                    json.dumps(proposal.current_value, default=str),
                    json.dumps(proposal.proposed_value, default=str),
                    proposal.rationale,
                    json.dumps(evidence_payload, default=str),
                    json.dumps(impact_payload, default=str) if impact_payload is not None else None,
                    proposal.validation_backtest_id,
                ),
            )
            ids.append(proposal_id)
        await conn.commit()
    log.info("rnd_proposals_inserted", count=len(ids), run_id=str(run_id))
    return ids


def parse_rnd_output(raw: str) -> RndAgentOutput:
    """Parse guard-approved JSON into :class:`RndAgentOutput`."""
    payload = json.loads(raw)
    return RndAgentOutput.model_validate(payload)


async def _fetch_all(
    conn: psycopg.AsyncConnection,
    sql: str,
    params: tuple[Any, ...] | None = None,
) -> list[dict[str, Any]]:
    cur = await conn.execute(sql, params or ())
    rows = await cur.fetchall()
    if not cur.description:
        return []
    columns = [desc.name for desc in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in rows]
