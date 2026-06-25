"""Cloudflare edge status API — read-only; no secrets exposed."""

from __future__ import annotations

import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, SettingsDep
from edge.service import EdgeRegistryService
from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter
from zinc_schemas.admin_dto import (
    CloudflareAccessAppsResponse,
    CloudflareDnsRoutesResponse,
    CloudflareStatusResponse,
    CloudflareTestRequest,
    CloudflareTestResponse,
    CloudflareTunnelsResponse,
    CloudflareWafEventsResponse,
    EdgeDriftReportResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/cloudflare", tags=["cloudflare"])


def _service(settings: SettingsDep) -> EdgeRegistryService:
    return EdgeRegistryService(settings)


def register_cloudflare_routes(limiter: Limiter) -> APIRouter:
    """Attach Cloudflare status endpoints."""

    @router.get("/status", response_model=CloudflareStatusResponse)
    async def cloudflare_status(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareStatusResponse:
        """Cloudflare + tunnel summary (redacted)."""
        payload = await _service(settings).cloudflare_status()
        log.info("cloudflare_status", sub=user["sub"], mode=payload.mode)
        return payload

    @router.get("/tunnels", response_model=CloudflareTunnelsResponse)
    async def cloudflare_tunnels(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareTunnelsResponse:
        return await _service(settings).cloudflare_tunnels()

    @router.get("/access/apps", response_model=CloudflareAccessAppsResponse)
    async def cloudflare_access_apps(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareAccessAppsResponse:
        return await _service(settings).cloudflare_access_apps()

    @router.get("/dns/routes", response_model=CloudflareDnsRoutesResponse)
    async def cloudflare_dns_routes(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareDnsRoutesResponse:
        return await _service(settings).cloudflare_dns_routes()

    @router.get("/routes", response_model=CloudflareDnsRoutesResponse)
    async def cloudflare_routes_alias(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareDnsRoutesResponse:
        """Alias for ``GET /admin/cloudflare/dns/routes``."""
        return await _service(settings).cloudflare_dns_routes()

    @router.get("/routes/drift", response_model=EdgeDriftReportResponse)
    async def cloudflare_routes_drift_alias(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> EdgeDriftReportResponse:
        """Alias for ``GET /admin/edge/routes/drift``."""
        return await _service(settings).drift_report()

    @router.get("/waf/events", response_model=CloudflareWafEventsResponse)
    async def cloudflare_waf_events(
        user: CurrentUser,
        settings: SettingsDep,
    ) -> CloudflareWafEventsResponse:
        return await _service(settings).cloudflare_waf_events()

    @router.post("/test", response_model=CloudflareTestResponse)
    @limiter.limit("20/minute")
    async def cloudflare_test(
        request: Request,  # noqa: ARG001
        body: CloudflareTestRequest,
        user: CurrentUser,
        settings: SettingsDep,
        conn: DbConn,
    ) -> CloudflareTestResponse:
        """Run edge drift + health checks; audit-logged; does not mutate Cloudflare."""
        svc = _service(settings)
        result = await svc.run_cloudflare_test()
        await write_audit_log(
            conn,
            actor=f"admin-api:{user['sub']}",
            action="cloudflare.test",
            entity_type="edge",
            entity_id="cloudflare",
            payload={"ok": result.ok, "mode": result.mode, "reason": body.reason},
        )
        log.info("cloudflare_test", sub=user["sub"], ok=result.ok)
        return result

    return router
