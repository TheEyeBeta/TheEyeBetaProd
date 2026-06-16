"""``GET /admin/ops/pulse`` — Command Center aggregation."""

from __future__ import annotations

import asyncio

import structlog
from deps import DbConn
from fastapi import APIRouter
from lib.queries.ops import (
    compute_health,
    fetch_audit_chain_status,
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
    AuditChainStatusSummary,
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


def _unwrap(result: object, fallback: object) -> object:
    """Return result or fallback if a gather task raised."""
    if isinstance(result, BaseException):
        log.warning("ops_pulse_partial_failure", error=str(result))
        return fallback
    return result


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
        (
            open_breakers,
            critical_alerts,
            last_runs,
            stale,
            freshness,
            pending,
            llm_cost,
            prelive,
            timers,
            services,
            audit_chain,
        ) = await asyncio.gather(
            fetch_open_breakers(conn),
            fetch_critical_alerts(conn),
            fetch_last_worker_runs(conn),
            fetch_stale_heartbeats(conn),
            fetch_pipeline_freshness(conn),
            fetch_pending_orders_count(conn),
            fetch_llm_cost_mtd(conn),
            fetch_prelive_last_result(conn),
            fetch_timers_summary(),
            _services_summary(),
            fetch_audit_chain_status(conn),
            return_exceptions=True,
        )

        audit_chain = _unwrap(
            audit_chain,
            {
                "last_verified_at": None,
                "valid": None,
                "entries_checked": 0,
                "error_message": None,
            },
        )

        open_breakers = _unwrap(open_breakers, [])
        critical_alerts = _unwrap(critical_alerts, [])
        last_runs = _unwrap(last_runs, [])
        stale = _unwrap(stale, [])
        freshness = _unwrap(freshness, {})
        pending = _unwrap(pending, 0)
        llm_cost = _unwrap(llm_cost, 0.0)
        prelive = _unwrap(
            prelive,
            {"passed": False, "run_at": None, "checks_passed": 0, "checks_failed": 0},
        )
        timers = _unwrap(timers, {"active": 0, "inactive": 0})
        services = _unwrap(services, ServicesSummary(healthy=0, degraded=0, down=0))

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
            pending_orders_count=int(pending),
            llm_cost_mtd_usd=float(llm_cost),
            prelive_last_result=PreliveLastResult(**prelive),
            timers_summary=TimersSummary(**timers),
            services_summary=services
            if isinstance(services, ServicesSummary)
            else ServicesSummary(**services),
            audit_chain_status=AuditChainStatusSummary(**audit_chain),
        )

    return router
