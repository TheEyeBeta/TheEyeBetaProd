"""Reports / briefings control plane."""

from __future__ import annotations

from uuid import UUID

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from rbac import MasterAdminUser, require_dangerous_confirm
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    ReportExportResponse,
    ReportListResponse,
    ReportRegenerateRequest,
    ReportRegenerateResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/reports", tags=["reports"])


def _intel(conn: DbConn, settings: SettingsDep):
    from intelligence_control.service import IntelligenceControlService

    return IntelligenceControlService(conn, settings)


def register_reports_routes(limiter: Limiter) -> APIRouter:
    """Attach briefing list, regenerate, and export endpoints."""

    @router.get("", response_model=None)
    async def reports_page_or_list(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> ReportListResponse:
        payload = await _intel(conn, settings).list_reports(limit=limit)
        if not prefers_html(request):
            return payload
        return templates.TemplateResponse(
            request,
            "reports.html",
            page_context(
                request,
                user=user,
                active="reports",
                title="Reports / Briefings",
                extra={
                    "listing": payload,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.post("/regenerate", response_model=ReportRegenerateResponse)
    @limiter.limit("5/minute")
    async def regenerate_report(
        request: Request,  # noqa: ARG001
        body: ReportRegenerateRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ReportRegenerateResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _intel(conn, settings).regenerate_report(
            body,
            actor=f"admin-api:{user['sub']}",
        )

    @router.get("/{report_id}/export", response_model=ReportExportResponse)
    async def export_report(
        report_id: UUID,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ReportExportResponse:
        try:
            return await _intel(conn, settings).export_report(report_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return router
