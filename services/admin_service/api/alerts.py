"""Audit alerts feed and acknowledgement APIs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import structlog
from audit_log import write_audit_log
from deps import DbConn
from fastapi import APIRouter, HTTPException, Query, Request, status
from rbac import Role, require_role
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    AlertAckRequest,
    AlertAckResponse,
    AlertEntry,
    AlertsListResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _actor(user: dict[str, str]) -> str:
    return f"admin-api:{user['sub']}"


def _ack_state(row: dict[str, Any]) -> str:
    if row.get("resolved_at"):
        return "resolved"
    if row.get("acknowledged_at"):
        return "acked"
    return "open"


async def fetch_alerts_page(
    conn: asyncpg.Connection,
    *,
    severity: str | None,
    status_filter: str | None,
    ack_state: str | None,
    source_worker: str | None,
    from_date: date | None,
    limit: int,
    offset: int,
) -> tuple[list[AlertEntry], int]:
    """Paginated audit alerts with filters."""
    clauses = ["1=1"]
    params: list[Any] = []
    idx = 1

    if severity:
        clauses.append(f"severity = ${idx}")
        params.append(severity.upper())
        idx += 1
    if source_worker:
        clauses.append(f"worker_name = ${idx}")
        params.append(source_worker)
        idx += 1
    if from_date:
        clauses.append(f"created_at >= ${idx}::timestamptz")
        params.append(datetime.combine(from_date, datetime.min.time(), tzinfo=UTC))
        idx += 1
    if ack_state == "open":
        clauses.append("acknowledged_at IS NULL AND resolved_at IS NULL")
    elif ack_state == "acked":
        clauses.append("acknowledged_at IS NOT NULL AND resolved_at IS NULL")
    elif ack_state == "resolved":
        clauses.append("resolved_at IS NOT NULL")
    if status_filter == "unresolved":
        clauses.append("resolved_at IS NULL")

    where = " AND ".join(clauses)
    total = await conn.fetchval(
        f"SELECT COUNT(*)::int FROM theeyebeta.audit_alerts WHERE {where}",  # noqa: S608
        *params,
    )
    params.extend([limit, offset])
    rows = await conn.fetch(
        f"""
        SELECT alert_id, severity, worker_name, title, message, created_at,
               acknowledged_by, acknowledged_at, gap_id, run_id, resolved_at
          FROM theeyebeta.audit_alerts
         WHERE {where}
         ORDER BY created_at DESC
         LIMIT ${idx} OFFSET ${idx + 1}
        """,  # noqa: S608
        *params,
    )
    alerts = [
        AlertEntry(
            id=row["alert_id"],
            severity=row["severity"],
            source=row["worker_name"] or "system",
            message=row["message"],
            title=row["title"],
            created_at=row["created_at"],
            ack_state=_ack_state(dict(row)),
            acked_by=row["acknowledged_by"],
            acked_at=row["acknowledged_at"],
            gap_id=row["gap_id"],
            run_id=row["run_id"],
        )
        for row in rows
    ]
    return alerts, int(total or 0)


def register_alerts_routes(limiter: Limiter) -> APIRouter:
    """Attach alert feed handlers."""

    @router.get(
        "",
        response_model=AlertsListResponse,
        summary="Alerts feed (READ_ONLY)",
    )
    async def list_alerts(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
        severity: str | None = Query(default=None),
        status: str | None = Query(default=None),
        ack_state: str | None = Query(default=None),
        source_worker: str | None = Query(default=None),
        from_date: date | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> AlertsListResponse:
        """Return paginated audit alerts."""
        alerts, total = await fetch_alerts_page(
            conn,
            severity=severity,
            status_filter=status,
            ack_state=ack_state,
            source_worker=source_worker,
            from_date=from_date,
            limit=limit,
            offset=offset,
        )
        log.info("admin_alerts_listed", total=total, sub=user["sub"])
        return AlertsListResponse(alerts=alerts, limit=limit, offset=offset, total=total)

    @router.post(
        "/{alert_id}/ack",
        response_model=AlertAckResponse,
        summary="Acknowledge alert (OPERATOR)",
    )
    @limiter.limit("30/minute")
    async def ack_alert(
        request: Request,  # noqa: ARG001
        alert_id: int,
        body: AlertAckRequest,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> AlertAckResponse:
        """Acknowledge an audit alert."""
        row = await conn.fetchrow(
            """
            SELECT alert_id, acknowledged_at
              FROM theeyebeta.audit_alerts
             WHERE alert_id = $1
            """,
            alert_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        if row["acknowledged_at"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already acknowledged")

        acked_at = datetime.now(tz=UTC)
        actor = _actor(user)
        await conn.execute(
            """
            UPDATE theeyebeta.audit_alerts
               SET acknowledged_by = $2,
                   acknowledged_at = $3,
                   updated_at = $3
             WHERE alert_id = $1
            """,
            alert_id,
            user["sub"],
            acked_at,
        )
        await write_audit_log(
            conn,
            actor=actor,
            action="ack.alert",
            entity_type="audit_alert",
            entity_id=str(alert_id),
            payload={"note": body.note, "acked_at": acked_at.isoformat()},
        )
        log.info("admin_alert_acked", alert_id=alert_id, sub=user["sub"])
        return AlertAckResponse(
            id=alert_id,
            ack_state="acked",
            acked_by=user["sub"],
            acked_at=acked_at,
        )

    return router
