"""Compliance / Legal cockpit API and HTML page."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from compliance_control.service import ComplianceControlService
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    actor_from_user,
    require_dangerous_confirm,
)
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    ComplianceCheckListResponse,
    ComplianceExceptionCreateRequest,
    ComplianceExceptionEntry,
    ComplianceExceptionListResponse,
    ComplianceHistoryResponse,
    ComplianceLegalHoldRequest,
    ComplianceLegalHoldResponse,
    ComplianceOverrideRequest,
    ComplianceOverrideResponse,
    ComplianceRecheckRequest,
    ComplianceRecheckResponse,
    ComplianceRulesPatchRequest,
    ComplianceRulesResponse,
    ComplianceStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/compliance", tags=["compliance"])


def _svc(conn: DbConn, settings: SettingsDep) -> ComplianceControlService:
    return ComplianceControlService(conn, settings)


def register_compliance_routes(limiter: Limiter) -> APIRouter:
    """Attach Compliance / Legal cockpit endpoints."""

    @router.get("", response_model=None)
    async def compliance_page_or_status(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> HTMLResponse | ComplianceStatusResponse:
        svc = _svc(conn, settings)
        status_payload = await svc.get_status(portfolio_id=portfolio_id)
        if not prefers_html(request):
            return status_payload
        checks = await svc.list_checks(portfolio_id=portfolio_id, limit=20)
        rules = await svc.get_rules()
        history = await svc.history(limit=30)
        exceptions = await svc.list_exceptions()
        overrides = await svc.list_overrides()
        holds = await svc.list_legal_holds()
        failed_rows = await svc.list_failed_checks(
            portfolio_id=status_payload.portfolio_id,
            limit=20,
        )
        log.info(
            "compliance_page_read",
            sub=user["sub"],
            portfolio=status_payload.portfolio_id,
            failed=status_payload.recent_failed_count,
        )
        return templates.TemplateResponse(
            request,
            "compliance.html",
            page_context(
                request,
                user=user,
                active="compliance",
                title="Legal/Compliance Cockpit",
                extra={
                    "status": status_payload,
                    "checks": checks,
                    "failed_checks": failed_rows,
                    "rules": rules,
                    "history": history,
                    "exceptions": exceptions,
                    "overrides": overrides,
                    "legal_holds": holds,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                    "compliance_links": [
                        {"label": "Guard violations", "href": "/admin/violations", "shipped": True},
                    ],
                },
            ),
        )

    @router.get("/status", response_model=ComplianceStatusResponse)
    async def compliance_status(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> ComplianceStatusResponse:
        payload = await _svc(conn, settings).get_status(portfolio_id=portfolio_id)
        log.info(
            "compliance_status_read",
            sub=user["sub"],
            portfolio=payload.portfolio_id,
            failed=payload.recent_failed_count,
        )
        return payload

    @router.get("/checks", response_model=ComplianceCheckListResponse)
    async def compliance_checks(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> ComplianceCheckListResponse:
        return await _svc(conn, settings).list_checks(portfolio_id=portfolio_id, limit=limit)

    @router.post("/checks/recheck", response_model=ComplianceRecheckResponse)
    @limiter.limit("5/minute")
    async def compliance_recheck(
        request: Request,  # noqa: ARG001
        body: ComplianceRecheckRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ComplianceRecheckResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        try:
            return await _svc(conn, settings).recheck(
                actor=actor_from_user(user),
                reason=body.reason,
                portfolio_id=body.portfolio_id,
                instrument_id=body.instrument_id,
                side=body.side,
                qty=body.qty,
                limit_price=body.limit_price,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.get("/rules", response_model=ComplianceRulesResponse)
    async def compliance_rules(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ComplianceRulesResponse:
        return await _svc(conn, settings).get_rules()

    @router.patch("/rules", response_model=ComplianceRulesResponse)
    @limiter.limit("10/minute")
    async def patch_compliance_rules(
        request: Request,  # noqa: ARG001
        body: ComplianceRulesPatchRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ComplianceRulesResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        return await _svc(conn, settings).patch_rules(body, actor=actor_from_user(user))

    @router.post("/override", response_model=ComplianceOverrideResponse)
    @limiter.limit("5/minute")
    async def compliance_override(
        request: Request,  # noqa: ARG001
        body: ComplianceOverrideRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ComplianceOverrideResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        return await _svc(conn, settings).override(body, actor=actor_from_user(user))

    @router.get("/exceptions", response_model=ComplianceExceptionListResponse)
    async def compliance_exceptions(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> ComplianceExceptionListResponse:
        return await _svc(conn, settings).list_exceptions()

    @router.post("/exceptions", response_model=ComplianceExceptionEntry)
    @limiter.limit("5/minute")
    async def create_compliance_exception(
        request: Request,  # noqa: ARG001
        body: ComplianceExceptionCreateRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ComplianceExceptionEntry:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        return await _svc(conn, settings).create_exception(body, actor=actor_from_user(user))

    @router.post("/legal-hold", response_model=ComplianceLegalHoldResponse)
    @limiter.limit("5/minute")
    async def compliance_legal_hold(
        request: Request,  # noqa: ARG001
        body: ComplianceLegalHoldRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> ComplianceLegalHoldResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        try:
            return await _svc(conn, settings).legal_hold(body, actor=actor_from_user(user))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.get("/history", response_model=ComplianceHistoryResponse)
    async def compliance_history(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> ComplianceHistoryResponse:
        return await _svc(conn, settings).history(limit=limit)

    return router
