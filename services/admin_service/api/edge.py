"""Edge Route Registry API."""

from __future__ import annotations

import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, SettingsDep
from edge.service import EdgeRegistryService
from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from zinc_schemas.admin_dto import (
    EdgeDriftReportResponse,
    EdgePortRegistryResponse,
    EdgeRouteDetailResponse,
    EdgeRouteListResponse,
    EdgeRoutesCheckRequest,
    EdgeRoutesCheckResponse,
    EdgeTrustedHostsResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/edge", tags=["edge"])


def _service(settings: SettingsDep) -> EdgeRegistryService:
    return EdgeRegistryService(settings)


def register_edge_routes(limiter: Limiter) -> APIRouter:
    """Attach Edge Route Registry endpoints."""

    @router.get("/routes", response_model=EdgeRouteListResponse)
    async def list_edge_routes(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgeRouteListResponse:
        payload = await _service(settings).list_routes()
        log.info("edge_routes_listed", sub=user["sub"], count=len(payload.routes))
        return payload

    @router.get("/routes/drift", response_model=EdgeDriftReportResponse)
    async def edge_routes_drift(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgeDriftReportResponse:
        return await _service(settings).drift_report()

    @router.get("/routes/{hostname}", response_model=EdgeRouteDetailResponse)
    async def get_edge_route(
        hostname: str,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgeRouteDetailResponse:
        detail = await _service(settings).get_route(hostname)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown edge route hostname: {hostname!r}",
            )
        return detail

    @router.post("/routes/check", response_model=EdgeRoutesCheckResponse)
    @limiter.limit("20/minute")
    async def edge_routes_check(
        request: Request,  # noqa: ARG001
        body: EdgeRoutesCheckRequest,
        user: CurrentUser,
        settings: SettingsDep,
        conn: DbConn,
    ) -> EdgeRoutesCheckResponse:
        """Refresh drift probes; audit-logged; read-only."""
        result = await _service(settings).run_routes_check()
        await write_audit_log(
            conn,
            actor=f"admin-api:{user['sub']}",
            action="edge.routes.check",
            entity_type="edge",
            entity_id="registry",
            payload={"ok": result.ok, "reason": body.reason},
        )
        log.info("edge_routes_check", sub=user["sub"], ok=result.ok)
        return result

    @router.get("/ports", response_model=EdgePortRegistryResponse)
    async def edge_ports(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgePortRegistryResponse:
        return await _service(settings).port_registry()

    @router.get("/trusted-hosts", response_model=EdgeTrustedHostsResponse)
    async def edge_trusted_hosts(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgeTrustedHostsResponse:
        return await _service(settings).trusted_hosts()

    return router
