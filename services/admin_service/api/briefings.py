"""Operator briefings API — chain-of-command reports addressed to the human operator."""

from __future__ import annotations

import structlog
from deps import DbConn
from fastapi import APIRouter, Query
from rbac import Role, require_role

from zinc_schemas.admin_dto import AgentReportSummary, BriefingsListResponse
from zinc_schemas.agent_reports import fetch_operator_briefings

log = structlog.get_logger()

router = APIRouter(prefix="/briefings", tags=["briefings"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


@router.get("", response_model=BriefingsListResponse)
async def list_operator_briefings(
    conn: DbConn,
    _user: dict[str, str] = require_role(Role.ANALYST),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
) -> BriefingsListResponse:
    """Return newest agent reports addressed to the operator."""
    rows = await fetch_operator_briefings(conn, limit=limit)
    briefings = [
        AgentReportSummary(
            id=row.id,
            agent_id=row.agent_id,
            audience=row.audience,
            run_id=row.run_id,
            report_type=row.report_type,
            summary=row.summary,
            payload=row.payload,
            status=row.status,
            created_at=row.created_at,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in rows
    ]
    log.info("admin_briefings_listed", count=len(briefings))
    return BriefingsListResponse(briefings=briefings, total=len(briefings))
