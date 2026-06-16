"""Trask dashboard and circuit breaker control APIs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg
import structlog
from audit_log import write_audit_log
from deps import DbConn
from fastapi import APIRouter, HTTPException, Request, status
from rbac import Role, require_role
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    BreakerResetRequest,
    BreakerResetResponse,
    TraskBreakerDetail,
    TraskDashboardResponse,
    TraskFailureSummary,
)

log = structlog.get_logger()

router = APIRouter(prefix="/trask", tags=["trask"])


def _actor(user: dict[str, str]) -> str:
    return f"admin-api:{user['sub']}"


def _breaker_reset_eligible(
    *,
    opened_at: datetime | None,
    recovery_timeout_seconds: int,
) -> bool:
    """Return whether enough time has passed to reset a breaker."""
    if opened_at is None:
        return True
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=UTC)
    elapsed = datetime.now(tz=UTC) - opened_at
    return elapsed >= timedelta(seconds=recovery_timeout_seconds)


async def fetch_trask_dashboard(conn: asyncpg.Connection) -> TraskDashboardResponse:
    """Aggregate Trask component and breaker state."""
    components = await conn.fetch(
        """
        SELECT component_id, state
          FROM theeyebeta.trask_components
        """,
    )
    healthy = sum(1 for c in components if c["state"] == "RUNNING")
    degraded = sum(1 for c in components if c["state"] == "DEGRADED")
    failed = sum(1 for c in components if c["state"] == "FAILED")

    breaker_rows = await conn.fetch(
        """
        SELECT id, component_id, state, failure_count, opened_at, config
          FROM theeyebeta.trask_circuit_breakers
         WHERE state = 'open'
         ORDER BY opened_at DESC NULLS LAST
        """,
    )
    open_breakers: list[TraskBreakerDetail] = []
    for row in breaker_rows:
        config = row["config"] or {}
        recovery = int(config.get("recovery_timeout_seconds", 300))
        opened = row["opened_at"]
        open_breakers.append(
            TraskBreakerDetail(
                id=row["id"],
                component_id=row["component_id"],
                state=row["state"],
                failure_count=row["failure_count"],
                opened_at=opened,
                reset_eligible=_breaker_reset_eligible(
                    opened_at=opened,
                    recovery_timeout_seconds=recovery,
                ),
                recovery_timeout_seconds=recovery,
            ),
        )

    degraded_ids = [c["component_id"] for c in components if c["state"] == "DEGRADED"]

    failure_rows = await conn.fetch(
        """
        SELECT DISTINCT ON (worker_name)
               worker_name, status, started_at, error_message
          FROM theeyebeta.worker_runs
         WHERE status IN ('FAILED', 'TIMEOUT')
         ORDER BY worker_name, started_at DESC
         LIMIT 20
        """,
    )
    recent_failures = [
        TraskFailureSummary(
            component_id=row["worker_name"],
            worker_name=row["worker_name"],
            status=row["status"],
            started_at=row["started_at"],
            error_message=row["error_message"],
        )
        for row in failure_rows
    ]

    return TraskDashboardResponse(
        components_total=len(components),
        components_healthy=healthy,
        components_degraded=degraded,
        components_failed=failed,
        open_breakers=open_breakers,
        degraded_components=degraded_ids,
        recent_failures=recent_failures,
    )


def register_trask_routes(limiter: Limiter) -> APIRouter:
    """Attach Trask dashboard and breaker reset handlers."""

    @router.get(
        "/dashboard",
        response_model=TraskDashboardResponse,
        summary="Trask dashboard (READ_ONLY)",
    )
    async def trask_dashboard(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
    ) -> TraskDashboardResponse:
        """Return Trask component health, breakers, and recent failures."""
        dashboard = await fetch_trask_dashboard(conn)
        log.info(
            "admin_trask_dashboard",
            open_breakers=len(dashboard.open_breakers),
            sub=user["sub"],
        )
        return dashboard

    @router.post(
        "/breakers/{breaker_id}/reset",
        response_model=BreakerResetResponse,
        summary="Reset circuit breaker (MASTER_ADMIN)",
    )
    @limiter.limit("10/minute")
    async def reset_breaker(
        request: Request,  # noqa: ARG001
        breaker_id: int,
        body: BreakerResetRequest,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> BreakerResetResponse:
        """Reset an open circuit breaker with audit trail."""
        if not body.consequences_acknowledged:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="consequences_acknowledged must be true",
            )

        row = await conn.fetchrow(
            """
            SELECT id, component_id, state, opened_at, config
              FROM theeyebeta.trask_circuit_breakers
             WHERE id = $1
            """,
            breaker_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Breaker not found")

        config = row["config"] or {}
        recovery = int(config.get("recovery_timeout_seconds", 300))
        if row["state"] == "open" and not _breaker_reset_eligible(
            opened_at=row["opened_at"],
            recovery_timeout_seconds=recovery,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Recovery timeout not elapsed; reset not eligible",
            )

        reset_at = datetime.now(tz=UTC)
        actor = _actor(user)
        await conn.execute(
            """
            UPDATE theeyebeta.trask_circuit_breakers
               SET state = 'closed',
                   failure_count = 0,
                   opened_at = NULL,
                   updated_at = $2
             WHERE id = $1
            """,
            breaker_id,
            reset_at,
        )

        await write_audit_log(
            conn,
            actor=actor,
            action="reset.breaker",
            entity_type="trask_circuit_breaker",
            entity_id=str(breaker_id),
            payload={
                "component_id": row["component_id"],
                "reason": body.reason,
                "override": body.override,
                "consequences_acknowledged": body.consequences_acknowledged,
                "actor": user["sub"],
                "reset_at": reset_at.isoformat(),
            },
        )

        log.info(
            "admin_breaker_reset",
            breaker_id=breaker_id,
            component=row["component_id"],
            sub=user["sub"],
        )
        return BreakerResetResponse(
            id=breaker_id,
            component_id=row["component_id"],
            state="closed",
            reset_at=reset_at,
            reset_by=user["sub"],
        )

    return router
