"""``GET /admin/ops/pulse`` — Command Center aggregation."""

from __future__ import annotations

import asyncio

import structlog
from deps import DbConn
from fastapi import APIRouter
from lib.queries.ops import (
    compute_health,
    fetch_critical_alerts,
    fetch_last_worker_runs,
    fetch_llm_cost_mtd,
    fetch_open_breakers,
    fetch_pending_orders_count,
    fetch_pipeline_freshness,
    fetch_prelive_last_result,
    fetch_stale_heartbeats,
)
from rbac import Role, require_role

from api.services import ALL_UNITS, _unit_to_entry
from api.timers import fetch_timers_summary
from zinc_schemas.admin_dto import (
    CriticalAlertSummary,
    OpenBreakerSummary,
    OpsPulseResponse,
    PipelineFreshness,
    PreliveLastResult,
    ServicesSummary,
    StaleHeartbeatSummary,
    TimersSummary,
    WorkerRunSummary,
)

log = structlog.get_logger()

router = APIRouter(prefix="/ops", tags=["ops"])


async def _services_summary() -> ServicesSummary:
    """Count systemd unit health states."""
    entries = await asyncio.gather(
        *[_unit_to_entry(name, unit) for name, unit in ALL_UNITS.items()],
    )
    healthy = sum(1 for e in entries if e.health == "healthy")
    down = sum(1 for e in entries if e.health != "healthy")
    return ServicesSummary(healthy=healthy, degraded=0, down=down)


def register_ops_routes() -> APIRouter:
    """Attach ops pulse handler."""

    @router.get(
        "/pulse",
        response_model=OpsPulseResponse,
        summary="Ops pulse (READ_ONLY)",
        description="Aggregated Command Center health snapshot. Requires READ_ONLY role minimum.",
    )
    async def ops_pulse(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
    ) -> OpsPulseResponse:
        """Return real-time ops aggregation from worker/trask/alert tables."""
        open_breakers = await fetch_open_breakers(conn)
        critical_alerts = await fetch_critical_alerts(conn)
        last_runs = await fetch_last_worker_runs(conn)
        stale = await fetch_stale_heartbeats(conn)
        freshness = await fetch_pipeline_freshness(conn)
        pending = await fetch_pending_orders_count(conn)
        llm_cost = await fetch_llm_cost_mtd(conn)
        prelive = await fetch_prelive_last_result(conn)
        timers = await fetch_timers_summary()
        services = await _services_summary()

        health = compute_health(
            open_breakers=open_breakers,
            critical_alerts=critical_alerts,
            stale_heartbeats=stale,
        )

        log.info("admin_ops_pulse", health=health, sub=user["sub"])
        return OpsPulseResponse(
            health=health,
            open_breakers=[OpenBreakerSummary(**row) for row in open_breakers],
            critical_alerts=[CriticalAlertSummary(**row) for row in critical_alerts],
            last_worker_runs=[WorkerRunSummary(**row) for row in last_runs],
            stale_heartbeats=[StaleHeartbeatSummary(**row) for row in stale],
            pipeline_freshness=PipelineFreshness(**freshness),
            pending_orders_count=pending,
            llm_cost_mtd_usd=llm_cost,
            prelive_last_result=PreliveLastResult(**prelive),
            timers_summary=TimersSummary(**timers),
            services_summary=services,
        )

    return router
