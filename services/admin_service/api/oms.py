"""OMS reconciliation API."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from blotter_control.service import BlotterService
from deps import DbConn, RedisOptionalDep, SettingsDep
from fastapi import APIRouter, Header, Request
from rbac import DangerousActionRequest, MasterAdminUser, actor_from_user, require_dangerous_confirm
from slowapi import Limiter
from zinc_schemas.admin_dto import (
    OmsReconciliationResolveResponse,
    OmsReconciliationResponse,
    OmsStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/oms", tags=["oms"])


def _svc(conn: DbConn, settings: SettingsDep, redis: RedisOptionalDep) -> BlotterService:
    return BlotterService(conn, settings, redis=redis)


def register_oms_routes(limiter: Limiter) -> APIRouter:
    """Attach OMS visibility and reconciliation endpoints."""

    @router.get("/status", response_model=OmsStatusResponse)
    async def oms_status(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> OmsStatusResponse:
        return await _svc(conn, settings, redis).oms_status()

    @router.get("/reconciliation", response_model=OmsReconciliationResponse)
    async def oms_reconciliation(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> OmsReconciliationResponse:
        return await _svc(conn, settings, redis).reconciliation_status()

    @router.post("/reconciliation/resolve", response_model=OmsReconciliationResolveResponse)
    @limiter.limit("5/minute")
    async def oms_reconciliation_resolve(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> OmsReconciliationResolveResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings, redis).resolve_reconciliation(
            actor=actor_from_user(user),
            reason=body.reason,
        )

    return router
