"""Universe pages — Cap Rank and Churn."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import SettingsDep
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from universe_control.service import UniverseControlService
from web import page_context, prefers_html, templates

log = structlog.get_logger()

router = APIRouter(prefix="/universe", tags=["universe"])


def register_universe_routes() -> APIRouter:
    """Attach the universe cap-rank and churn pages."""

    @router.get("/caps", response_model=None, include_in_schema=False)
    async def universe_caps_page(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
        min_market_cap: float = Query(default=500_000_000, ge=0),
    ) -> HTMLResponse | dict[str, object]:
        svc = UniverseControlService(settings)
        data = await svc.get_active(min_market_cap=min_market_cap, limit=200)
        log.info("universe_caps_read", sub=user["sub"], entries=len(data["entries"]))
        if not prefers_html(request):
            return data
        return templates.TemplateResponse(
            request,
            "universe_caps.html",
            page_context(
                request,
                user=user,
                active="universe-caps",
                title="Universe Caps",
                extra={
                    "as_of_date": data["as_of_date"],
                    "entries": data["entries"],
                    "error": data["error"],
                    "min_market_cap": min_market_cap,
                },
            ),
        )

    @router.get("/churn", response_model=None, include_in_schema=False)
    async def universe_churn_page(
        request: Request,
        user: CurrentUser,
        settings: SettingsDep,
    ) -> HTMLResponse | dict[str, object]:
        svc = UniverseControlService(settings)
        data = await svc.get_cap_events(limit=100)
        log.info("universe_churn_read", sub=user["sub"], events=len(data["events"]))
        if not prefers_html(request):
            return data
        return templates.TemplateResponse(
            request,
            "universe_churn.html",
            page_context(
                request,
                user=user,
                active="universe-churn",
                title="Universe Churn",
                extra={
                    "events": data["events"],
                    "error": data["error"],
                },
            ),
        )

    return router
