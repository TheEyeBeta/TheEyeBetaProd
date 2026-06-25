"""Cloudflare / Edge operator page (htmx)."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import SettingsDep
from edge.service import EdgeRegistryService
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from web import page_context, templates

log = structlog.get_logger()

router = APIRouter(tags=["edge-views"])


def register_edge_views() -> APIRouter:
    """HTML routes for the Cloudflare/Edge control plane."""

    @router.get("/edge", response_class=HTMLResponse, include_in_schema=False)
    async def edge_page(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> HTMLResponse:
        svc = EdgeRegistryService(settings)
        routes = await svc.list_routes()
        drift = svc.drift_report_for_routes(routes.routes)
        status = await svc.cloudflare_status(routes.routes)
        trusted = await svc.trusted_hosts()
        log.info("edge_page_rendered", sub=user["sub"], mode=status.mode)
        return templates.TemplateResponse(
            request,
            "edge.html",
            page_context(
                request,
                user=user,
                active="edge",
                title="Cloudflare / Edge",
                extra={
                    "cf_status": status,
                    "routes": routes,
                    "drift": drift,
                    "trusted": trusted,
                },
            ),
        )

    @router.get("/edge/fragments/status", response_class=HTMLResponse, include_in_schema=False)
    async def edge_status_fragment(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> HTMLResponse:
        svc = EdgeRegistryService(settings)
        routes = await svc.list_routes()
        drift = svc.drift_report_for_routes(routes.routes)
        status = await svc.cloudflare_status(routes.routes)
        trusted = await svc.trusted_hosts()
        return templates.TemplateResponse(
            request,
            "components/_edge_status_panel.html",
            {
                "request": request,
                "cf_status": status,
                "routes": routes,
                "drift": drift,
                "trusted": trusted,
            },
        )

    return router
