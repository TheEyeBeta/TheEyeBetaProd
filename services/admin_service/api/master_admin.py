"""MASTER_ADMIN control matrix API and HTML pages."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from control_matrix.registry import build_control_matrix_response
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from web import page_context, templates
from zinc_schemas.admin_dto import ControlMatrixResponse

log = structlog.get_logger()

router = APIRouter(prefix="/master-admin", tags=["master-admin"])


def register_master_admin_routes() -> APIRouter:
    """Attach control-matrix JSON + HTML handlers."""

    @router.get("/control-matrix", response_model=ControlMatrixResponse)
    async def get_control_matrix(
        user: CurrentUser,
        category: str | None = Query(default=None, max_length=120),
        priority: str | None = Query(default=None, max_length=32),
    ) -> ControlMatrixResponse:
        """Return the full MASTER_ADMIN control matrix."""
        payload = build_control_matrix_response()
        entries = payload.entries
        if category:
            entries = [e for e in entries if e.category == category]
        if priority:
            entries = [e for e in entries if e.priority == priority]
        log.info(
            "control_matrix_listed",
            sub=user["sub"],
            count=len(entries),
            category=category,
            priority=priority,
        )
        return ControlMatrixResponse(
            version=payload.version,
            generated_at=payload.generated_at,
            entries=entries,
            categories=payload.categories,
            drift_alerts=payload.drift_alerts,
        )

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def master_admin_page(
        request: Request,
        user: CurrentUser,
        category: str | None = Query(default=None, max_length=120),
    ) -> HTMLResponse:
        """MASTER_ADMIN control matrix page."""
        payload = build_control_matrix_response()
        entries = payload.entries
        if category:
            entries = [e for e in entries if e.category == category]
        categories = sorted({e.category for e in payload.entries})
        return templates.TemplateResponse(
            request,
            "master_admin.html",
            page_context(
                request,
                user=user,
                active="master-admin",
                title="MASTER_ADMIN",
                extra={
                    "matrix": payload,
                    "entries": entries,
                    "categories": categories,
                    "filter_category": category,
                    "drift_alerts": payload.drift_alerts,
                },
            ),
        )

    @router.get("/fragments/matrix", response_class=HTMLResponse, include_in_schema=False)
    async def master_admin_matrix_fragment(
        request: Request,
        user: CurrentUser,
        category: str | None = Query(default=None, max_length=120),
        priority: str | None = Query(default=None, max_length=32),
    ) -> HTMLResponse:
        """htmx fragment: filtered matrix table."""
        payload = build_control_matrix_response()
        entries = payload.entries
        if category:
            entries = [e for e in entries if e.category == category]
        if priority:
            entries = [e for e in entries if e.priority == priority]
        return templates.TemplateResponse(
            request,
            "components/_control_matrix_table.html",
            {
                "request": request,
                "entries": entries,
                "drift_alerts": payload.drift_alerts,
            },
        )

    return router
