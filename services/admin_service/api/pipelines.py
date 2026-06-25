"""Data pipeline visibility — worker runs and ingestion metrics."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from market_control.service import MarketControlService
from slowapi import Limiter
from web import page_context, prefers_html, templates

log = structlog.get_logger()

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _svc(conn: DbConn, settings: SettingsDep) -> MarketControlService:
    return MarketControlService(conn, settings)


def register_pipelines_routes(limiter: Limiter) -> APIRouter:  # noqa: ARG001
    """Attach pipeline hub page and JSON status."""

    @router.get("", response_model=None)
    async def pipelines_page_or_status(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse | dict[str, object]:
        svc = _svc(conn, settings)
        payload = await svc.pipeline_status()
        if not prefers_html(request):
            return payload
        market_status = await svc.get_status()
        log.info("pipelines_page_read", sub=user["sub"])
        return templates.TemplateResponse(
            request,
            "pipelines.html",
            page_context(
                request,
                user=user,
                active="pipelines",
                title="Data Pipelines",
                extra={
                    "pipeline": payload,
                    "market_status": market_status,
                    "worker_link": "/admin/workers",
                    "market_data_link": "/admin/market-data",
                },
            ),
        )

    return router
