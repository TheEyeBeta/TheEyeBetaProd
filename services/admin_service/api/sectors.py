"""Sector aggregate pages — Rotation, Breadth, Performance."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import SettingsDep
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from sector_control.service import SectorControlService
from web import page_context, prefers_html, templates

log = structlog.get_logger()

router = APIRouter(prefix="/sectors", tags=["sectors"])

_VIEWS: dict[str, tuple[str, str]] = {
    "rotation": ("sector-rotation", "Sector Rotation"),
    "breadth": ("sector-breadth", "Sector Breadth"),
    "performance": ("sector-performance", "Sector Performance"),
}


def register_sectors_routes() -> APIRouter:
    """Attach the sector aggregate pages."""

    def _make_handler(view: str, module_key: str, title: str):
        @router.get(f"/{view}", response_model=None, include_in_schema=False)
        async def _sector_view_page(
            request: Request,
            user: CurrentUser,
            settings: SettingsDep,
            sector: str | None = Query(default=None),
        ) -> HTMLResponse | dict[str, object]:
            svc = SectorControlService(settings)
            limit = 252 if view == "performance" and sector else 50
            data = await svc.get_daily(sector=sector if view == "performance" else None, limit=limit)
            log.info("sector_view_read", sub=user["sub"], view=view, sector=sector)
            if not prefers_html(request):
                return data
            return templates.TemplateResponse(
                request,
                "sectors.html",
                page_context(
                    request,
                    user=user,
                    active=module_key,
                    title=title,
                    extra={
                        "view": view,
                        "sectors": data["sectors"],
                        "error": data["error"],
                        "selected_sector": sector,
                    },
                ),
            )

        return _sector_view_page

    for view, (module_key, title) in _VIEWS.items():
        _make_handler(view, module_key, title)

    return router
