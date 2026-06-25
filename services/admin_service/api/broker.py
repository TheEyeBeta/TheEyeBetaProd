"""Broker / Portfolio blotter API and HTML page."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from blotter_control.service import BlotterService
from deps import DbConn, RedisOptionalDep, SettingsDep
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import HTMLResponse
from rbac import DangerousActionRequest, MasterAdminUser, actor_from_user, require_dangerous_confirm
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    BrokerAccountResponse,
    BrokerFillsResponse,
    BrokerOrdersResponse,
    BrokerPositionsResponse,
    BrokerStatusResponse,
    BrokerTestConnectionResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/broker", tags=["broker"])


def _svc(conn: DbConn, settings: SettingsDep, redis: RedisOptionalDep) -> BlotterService:
    return BlotterService(conn, settings, redis=redis)


def register_broker_routes(limiter: Limiter) -> APIRouter:
    """Attach broker blotter endpoints."""

    @router.get("", response_model=None)
    async def broker_page_or_status(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> HTMLResponse | BrokerStatusResponse:
        svc = _svc(conn, settings, redis)
        status_payload = await svc.broker_status()
        if not prefers_html(request):
            return status_payload
        account = await svc.broker_account()
        positions = await svc.broker_positions(source="both")
        fills = await svc.broker_fills(limit=30)
        broker_orders = await svc.broker_orders_proxy()
        return templates.TemplateResponse(
            request,
            "broker.html",
            page_context(
                request,
                user=user,
                active="broker",
                title="Broker / Portfolio",
                extra={
                    "status": status_payload,
                    "account": account,
                    "positions": positions,
                    "fills": fills,
                    "broker_orders": broker_orders,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                },
            ),
        )

    @router.get("/status", response_model=BrokerStatusResponse)
    async def broker_status(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> BrokerStatusResponse:
        return await _svc(conn, settings, redis).broker_status()

    @router.get("/account", response_model=BrokerAccountResponse)
    async def broker_account(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> BrokerAccountResponse:
        return await _svc(conn, settings, redis).broker_account()

    @router.get("/positions", response_model=BrokerPositionsResponse)
    async def broker_positions(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        source: str = Query(default="both"),
    ) -> BrokerPositionsResponse:
        return await _svc(conn, settings, redis).broker_positions(source=source)

    @router.get("/orders", response_model=BrokerOrdersResponse)
    async def broker_orders(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
    ) -> BrokerOrdersResponse:
        return await _svc(conn, settings, redis).broker_orders_proxy()

    @router.get("/fills", response_model=BrokerFillsResponse)
    async def broker_fills(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> BrokerFillsResponse:
        return await _svc(conn, settings, redis).broker_fills(limit=limit)

    @router.post("/test-connection", response_model=BrokerTestConnectionResponse)
    @limiter.limit("5/minute")
    async def broker_test_connection(
        request: Request,  # noqa: ARG001
        body: DangerousActionRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        redis: RedisOptionalDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> BrokerTestConnectionResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings, redis).test_connection(
            actor=actor_from_user(user),
            reason=body.reason,
        )

    return router
