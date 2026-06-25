"""Risk cockpit control plane API and HTML page."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    actor_from_user,
    require_dangerous_confirm,
)
from risk_control.service import RiskControlService
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    RiskBreachListResponse,
    RiskComputeResponse,
    RiskFailureListResponse,
    RiskHistoryResponse,
    RiskLimitPatchRequest,
    RiskLimitsResponse,
    RiskMetricsResponse,
    RiskOverrideRequest,
    RiskOverrideResponse,
    RiskStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/risk", tags=["risk"])


def _svc(conn: DbConn, settings: SettingsDep) -> RiskControlService:
    return RiskControlService(conn, settings)


def register_risk_routes(limiter: Limiter) -> APIRouter:
    """Attach Risk cockpit endpoints."""

    @router.get("", response_model=None)
    async def risk_page_or_status(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> HTMLResponse | RiskStatusResponse:
        svc = _svc(conn, settings)
        status_payload = await svc.get_status(portfolio_id=portfolio_id)
        if not prefers_html(request):
            return status_payload
        breaches = await svc.list_breaches(portfolio_id=portfolio_id)
        failures = await svc.list_failures()
        limits = await svc.get_limits()
        history = await svc.history(limit=30)
        overrides = await svc.list_overrides()
        log.info(
            "risk_page_read",
            sub=user["sub"],
            portfolio=status_payload.portfolio_id,
            breaches=len(breaches.breaches),
        )
        return templates.TemplateResponse(
            request,
            "risk.html",
            page_context(
                request,
                user=user,
                active="risk",
                title="Risk Cockpit",
                extra={
                    "status": status_payload,
                    "breaches": breaches,
                    "failures": failures,
                    "limits": limits,
                    "history": history,
                    "overrides": overrides,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.get("/status", response_model=RiskStatusResponse)
    async def risk_status(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> RiskStatusResponse:
        payload = await _svc(conn, settings).get_status(portfolio_id=portfolio_id)
        log.info(
            "risk_status_read",
            sub=user["sub"],
            portfolio=payload.portfolio_id,
            breaches=payload.active_breach_count,
        )
        return payload

    @router.get("/metrics", response_model=RiskMetricsResponse)
    async def risk_metrics(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> RiskMetricsResponse:
        return await _svc(conn, settings).get_metrics(portfolio_id=portfolio_id)

    @router.get("/limits", response_model=RiskLimitsResponse)
    async def risk_limits(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> RiskLimitsResponse:
        return await _svc(conn, settings).get_limits()

    @router.patch("/limits", response_model=RiskLimitsResponse)
    @limiter.limit("10/minute")
    async def patch_risk_limits(
        request: Request,  # noqa: ARG001
        body: RiskLimitPatchRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> RiskLimitsResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        return await _svc(conn, settings).patch_limits(body, actor=actor_from_user(user))

    @router.get("/breaches", response_model=RiskBreachListResponse)
    async def risk_breaches(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        portfolio_id: str | None = Query(default=None),
    ) -> RiskBreachListResponse:
        return await _svc(conn, settings).list_breaches(portfolio_id=portfolio_id)

    @router.get("/failures", response_model=RiskFailureListResponse)
    async def risk_failures(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> RiskFailureListResponse:
        return await _svc(conn, settings).list_failures()

    @router.get("/history", response_model=RiskHistoryResponse)
    async def risk_history(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> RiskHistoryResponse:
        return await _svc(conn, settings).history(limit=limit)

    @router.post("/compute", response_model=RiskComputeResponse)
    @limiter.limit("5/minute")
    async def risk_compute(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
        portfolio_id: str | None = Query(default=None),
    ) -> RiskComputeResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _svc(conn, settings).compute(
                actor=actor_from_user(user),
                reason=body.reason,
                portfolio_id=portfolio_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.post("/override", response_model=RiskOverrideResponse)
    @limiter.limit("5/minute")
    async def risk_override(
        request: Request,  # noqa: ARG001
        body: RiskOverrideRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> RiskOverrideResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        return await _svc(conn, settings).override(body, actor=actor_from_user(user))

    @router.post("/trading-lock", response_model=RiskStatusResponse)
    @limiter.limit("10/minute")
    async def risk_trading_lock(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> RiskStatusResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings).set_trading_lock(
            actor=actor_from_user(user),
            reason=body.reason,
            locked=True,
        )

    @router.post("/trading-unlock", response_model=RiskStatusResponse)
    @limiter.limit("10/minute")
    async def risk_trading_unlock(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> RiskStatusResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings).set_trading_lock(
            actor=actor_from_user(user),
            reason=body.reason,
            locked=False,
        )

    return router
