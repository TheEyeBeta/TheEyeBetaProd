"""Emergency Trading control plane API."""

from __future__ import annotations

import structlog
from deps import DbConn, RedisOptionalDep, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from rbac import (
    DangerousActionRequest,
    MasterAdminUser,
    actor_from_user,
    require_dangerous_confirm,
)
from slowapi import Limiter
from trading_control.service import TradingControlService
from web import page_context, templates
from zinc_schemas.admin_dto import (
    LiveApprovalRequest,
    LiveApprovalTokenResponse,
    TradingEventListResponse,
    TradingGateHistoryResponse,
    TradingStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/trading", tags=["trading"])
emergency_router = APIRouter(tags=["emergency-trading"])


def _svc(conn: DbConn, settings: SettingsDep, redis: RedisOptionalDep) -> TradingControlService:
    return TradingControlService(conn, settings, redis=redis)


def register_trading_routes(limiter: Limiter) -> APIRouter:
    """Attach Emergency Trading endpoints."""

    @emergency_router.get("/emergency", response_class=HTMLResponse, include_in_schema=False)
    async def emergency_trading_page(
        request: Request,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> HTMLResponse:
        status_payload = await _svc(conn, settings, redis).get_status()
        events = await _svc(conn, settings, redis).list_events(limit=30)
        gate_history = await _svc(conn, settings, redis).gate_history(limit=20)
        return templates.TemplateResponse(
            request,
            "emergency.html",
            page_context(
                request,
                user=user,
                active="emergency",
                title="Emergency Trading",
                extra={
                    "status": status_payload,
                    "events": events,
                    "gate_history": gate_history,
                },
            ),
        )

    @router.get("/status", response_model=TradingStatusResponse)
    async def trading_status(
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> TradingStatusResponse:
        payload = await _svc(conn, settings, redis).get_status()
        log.info("trading_status_read", sub=user["sub"], halt=payload.emergency_halt)
        return payload

    @router.get("/events", response_model=TradingEventListResponse)
    async def trading_events(
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> TradingEventListResponse:
        return await _svc(conn, settings, redis).list_events()

    @router.get("/gate-history", response_model=TradingGateHistoryResponse)
    async def trading_gate_history(
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> TradingGateHistoryResponse:
        return await _svc(conn, settings, redis).gate_history()

    @router.post("/live-approval-token", response_model=LiveApprovalTokenResponse)
    @limiter.limit("5/minute")
    async def issue_live_approval_token(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> LiveApprovalTokenResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings, redis).issue_live_approval_token(
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/live-approval", response_model=TradingStatusResponse)
    @limiter.limit("5/minute")
    async def approve_live_trading(
        request: Request,  # noqa: ARG001
        body: LiveApprovalRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TradingStatusResponse:
        require_dangerous_confirm(
            DangerousActionRequest(reason=body.reason, confirm=body.confirm),
            x_confirm,
        )
        try:
            return await _svc(conn, settings, redis).approve_live_trading(
                body,
                actor=actor_from_user(user),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.post("/emergency-halt", response_model=TradingStatusResponse)
    @limiter.limit("10/minute")
    async def emergency_halt(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TradingStatusResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings, redis).emergency_halt(
            actor=actor_from_user(user),
            reason=body.reason,
        )

    @router.post("/resume-from-halt", response_model=TradingStatusResponse)
    @limiter.limit("10/minute")
    async def resume_from_halt(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> TradingStatusResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _svc(conn, settings, redis).resume_from_halt(
                actor=actor_from_user(user),
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return router
