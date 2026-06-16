"""Admin agents API — registry, runs, manual trigger, constitution viewer."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncpg
import httpx
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, Query, Request, status
from rbac import Role, require_role
from slowapi import Limiter

if TYPE_CHECKING:
    from settings import Settings

from zinc_schemas.admin_dto import (
    AgentConstitutionResponse,
    AgentRunRow,
    AgentRunsResponse,
    AgentsListResponse,
    AgentSummary,
    RunAgentRequest,
    RunAgentResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])

_DEFAULT_RUNS_LIMIT = 50
_MAX_RUNS_LIMIT = 200
_RUNTIME_TIMEOUT_SECONDS = 120.0


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


async def _agent_exists(conn: asyncpg.Connection, agent_id: str) -> bool:
    """Return True if an agent registry row exists."""
    row = await conn.fetchrow(
        "SELECT 1 FROM theeyebeta.agents WHERE id = $1",
        agent_id,
    )
    return row is not None


async def fetch_agents_summary(conn: asyncpg.Connection) -> list[AgentSummary]:
    """Return the registry + 7-day run aggregates as :class:`AgentSummary` rows.

    Shared by the JSON ``GET /admin/agents`` route and the HTML view-router
    handler so both surfaces emit the same shape and aggregates.
    """
    rows = await conn.fetch(
        """
        WITH recent AS (
            SELECT
                agent_id,
                MAX(started_at)                                              AS last_run_at,
                COUNT(*) FILTER (
                    WHERE started_at >= now() - interval '7 days'
                )::int                                                       AS runs_7d,
                COUNT(*) FILTER (
                    WHERE started_at >= now() - interval '7 days'
                      AND status = 'succeeded'
                )::int                                                       AS ok_7d
              FROM theeyebeta.agent_runs
             GROUP BY agent_id
        )
        SELECT
            a.id,
            a.department,
            a.role,
            a.model_default,
            a.model_fallback,
            a.constitution_path,
            a.active,
            r.last_run_at,
            COALESCE(r.runs_7d, 0)::int AS runs_7d,
            CASE
                WHEN COALESCE(r.runs_7d, 0) = 0 THEN NULL
                ELSE r.ok_7d::float / r.runs_7d::float
            END AS success_rate_7d
          FROM theeyebeta.agents a
          LEFT JOIN recent r ON r.agent_id = a.id
         ORDER BY a.id
        """,
    )
    return [
        AgentSummary(
            id=row["id"],
            department=row["department"],
            role=row["role"],
            model_default=row["model_default"],
            model_fallback=row["model_fallback"],
            constitution_path=row["constitution_path"],
            active=bool(row["active"]),
            last_run_at=row["last_run_at"],
            runs_7d=int(row["runs_7d"]),
            success_rate_7d=(
                float(row["success_rate_7d"]) if row["success_rate_7d"] is not None else None
            ),
        )
        for row in rows
    ]


async def fetch_agent_runs(
    conn: asyncpg.Connection,
    agent_id: str,
    limit: int = _DEFAULT_RUNS_LIMIT,
) -> AgentRunsResponse:
    """Return ``AgentRunsResponse`` for one agent or raise 404 if unknown."""
    if not await _agent_exists(conn, agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    rows = await conn.fetch(
        """
        SELECT id, agent_id, triggered_by, parent_run_id, snapshot_id,
               started_at, ended_at, status,
               total_input_tokens, total_output_tokens, total_cost_usd, error
          FROM theeyebeta.agent_runs
         WHERE agent_id = $1
         ORDER BY started_at DESC
         LIMIT $2
        """,
        agent_id,
        limit,
    )
    runs = [
        AgentRunRow(
            id=row["id"],
            agent_id=row["agent_id"],
            triggered_by=row["triggered_by"],
            parent_run_id=row["parent_run_id"],
            snapshot_id=row["snapshot_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            total_input_tokens=row["total_input_tokens"],
            total_output_tokens=row["total_output_tokens"],
            total_cost_usd=(
                Decimal(str(row["total_cost_usd"])) if row["total_cost_usd"] is not None else None
            ),
            error=row["error"],
        )
        for row in rows
    ]
    return AgentRunsResponse(agent_id=agent_id, runs=runs, limit=limit)


async def read_agent_constitution(
    conn: asyncpg.Connection,
    repo_root: Path,
    agent_id: str,
) -> AgentConstitutionResponse:
    """Return the agent's constitution markdown or raise 404."""
    row = await conn.fetchrow(
        """
        SELECT id, constitution_path
          FROM theeyebeta.agents
         WHERE id = $1
        """,
        agent_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    target = _resolve_constitution_path(repo_root, row["constitution_path"])
    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("admin_constitution_read_failed", agent_id=agent_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read constitution",
        ) from exc
    return AgentConstitutionResponse(
        agent_id=row["id"],
        constitution_path=row["constitution_path"],
        content=content,
    )


async def trigger_agent_run_impl(
    conn: asyncpg.Connection,
    settings: Settings,
    agent_id: str,
    *,
    body: RunAgentRequest,
    actor: str,
) -> RunAgentResponse:
    """Proxy to ``agent-runtime``, audit log the trigger, return the response.

    Shared by the JSON ``POST /admin/agents/{id}/run`` route and the HTML
    view-router "Run Now" fragment.
    """
    if not await _agent_exists(conn, agent_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    audit_payload = body.model_dump(mode="json")
    runtime_payload = {
        "snapshot_id": str(body.snapshot_id),
        "kind": body.kind,
        "agent_messages": [m.model_dump() for m in body.agent_messages],
    }
    url = f"{settings.agent_runtime_url.rstrip('/')}/agents/{agent_id}/run"
    try:
        async with httpx.AsyncClient(timeout=_RUNTIME_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=runtime_payload)
    except httpx.HTTPError as exc:
        log.error("agent_runtime_unreachable", url=url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent-runtime is unreachable",
        ) from exc

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=response.text,
        )
    if response.status_code == status.HTTP_409_CONFLICT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=response.text,
        )
    if response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.text,
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent-runtime returned 5xx",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    data: dict[str, Any] = response.json()
    run_id = str(data.get("run_id") or "")
    if not run_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="agent-runtime response missing run_id",
        )

    await write_audit_log(
        conn,
        actor=actor,
        action="run.agent",
        entity_type="agent",
        entity_id=agent_id,
        payload={**audit_payload, "run_id": run_id},
    )
    return RunAgentResponse(**data)


def _resolve_constitution_path(repo_root: Path, raw: str) -> Path:
    """Resolve a constitution path under ``repo_root`` and reject traversal.

    Args:
        repo_root: Repository root used as the trust boundary.
        raw: ``constitution_path`` column value (may be relative or absolute).

    Returns:
        Absolute :class:`Path` inside ``repo_root``.

    Raises:
        HTTPException: 422 when the resolved path escapes ``repo_root`` and 404
            when the file does not exist.
    """
    candidate = Path(raw)
    target = candidate if candidate.is_absolute() else (repo_root / candidate)
    target = target.resolve()
    repo_resolved = repo_root.resolve()
    try:
        target.relative_to(repo_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="constitution_path escapes repository root",
        ) from exc
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Constitution file not found",
        )
    return target


def register_agents_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited agent handlers to the shared router."""

    @router.get("", response_model=AgentsListResponse)
    async def list_agents(
        user: CurrentUser,
        conn: DbConn,
    ) -> AgentsListResponse:
        """List all agents with last-run and 7-day success aggregates."""
        agents = await fetch_agents_summary(conn)
        log.info("admin_agents_listed", count=len(agents), sub=user["sub"])
        return AgentsListResponse(agents=agents)

    @router.get("/{agent_id}/runs", response_model=AgentRunsResponse)
    async def list_agent_runs(
        agent_id: str,
        user: CurrentUser,
        conn: DbConn,
        limit: int = Query(default=_DEFAULT_RUNS_LIMIT, ge=1, le=_MAX_RUNS_LIMIT),
    ) -> AgentRunsResponse:
        """Return the most recent ``agent_runs`` rows for one agent."""
        result = await fetch_agent_runs(conn, agent_id, limit)
        log.info(
            "admin_agent_runs_listed",
            agent_id=agent_id,
            count=len(result.runs),
            sub=user["sub"],
        )
        return result

    @router.post("/{agent_id}/run", response_model=RunAgentResponse)
    @limiter.limit("20/minute")
    async def trigger_agent_run(
        request: Request,  # noqa: ARG001 — required by slowapi
        agent_id: str,
        body: RunAgentRequest,
        conn: DbConn,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> RunAgentResponse:
        """Forward to ``agent-runtime`` and audit log the trigger."""
        result = await trigger_agent_run_impl(
            conn,
            settings,
            agent_id=agent_id,
            body=body,
            actor=_actor(user),
        )
        log.info(
            "admin_agent_run_triggered",
            agent_id=agent_id,
            run_id=result.run_id,
            sub=user["sub"],
        )
        return result

    @router.get("/{agent_id}/constitution", response_model=AgentConstitutionResponse)
    async def get_agent_constitution(
        agent_id: str,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> AgentConstitutionResponse:
        """Return the constitution markdown for an agent."""
        response = await read_agent_constitution(
            conn,
            settings.repo_root_path(),
            agent_id,
        )
        log.info(
            "admin_agent_constitution_fetched",
            agent_id=agent_id,
            path=response.constitution_path,
            sub=user["sub"],
        )
        return response

    return router
