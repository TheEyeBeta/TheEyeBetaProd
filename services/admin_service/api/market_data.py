"""Market data quality cockpit API and HTML page."""

from __future__ import annotations

import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from market_control.service import MarketControlService
from rbac import MasterAdminUser, actor_from_user, require_dangerous_confirm
from slowapi import Limiter
from web import page_context, prefers_html, templates
from zinc_schemas.admin_dto import (
    MarketBackfillRequest,
    MarketBackfillResponse,
    MarketCapEventsResponse,
    MarketDataGapListResponse,
    MarketDataGapResolveRequest,
    MarketDataGapResolveResponse,
    MarketDataProvidersResponse,
    MarketDataStatusResponse,
    MarketUniverseResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/market-data", tags=["market-data"])


def _svc(conn: DbConn, settings: SettingsDep) -> MarketControlService:
    return MarketControlService(conn, settings)


def register_market_data_routes(limiter: Limiter) -> APIRouter:
    """Attach market data visibility and operator endpoints."""

    @router.get("", response_model=None)
    async def market_data_page_or_status(
        request: Request,
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> HTMLResponse | MarketDataStatusResponse:
        svc = _svc(conn, settings)
        status_payload = await svc.get_status()
        if not prefers_html(request):
            return status_payload
        providers = await svc.list_providers()
        gaps = await svc.list_gaps(limit=30)
        universe = await svc.get_universe()
        cap_events = await svc.market_cap_events(limit=15)
        events = await svc.recent_events(limit=20)
        log.info(
            "market_data_page_read",
            sub=user["sub"],
            open_gaps=status_payload.open_gap_count,
            stale=len(status_payload.stale_datasets),
        )
        return templates.TemplateResponse(
            request,
            "market_data.html",
            page_context(
                request,
                user=user,
                active="market",
                title="Market Data",
                extra={
                    "status": status_payload,
                    "providers": providers,
                    "gaps": gaps,
                    "universe": universe,
                    "cap_events": cap_events,
                    "events": events,
                    "is_master_admin": "MASTER_ADMIN" in (user.get("roles") or []),
                    "data_api_link": "/admin/data-api",
                },
            ),
        )

    @router.get("/status", response_model=MarketDataStatusResponse)
    async def market_data_status(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> MarketDataStatusResponse:
        payload = await _svc(conn, settings).get_status()
        log.info(
            "market_data_status_read",
            sub=user["sub"],
            open_gaps=payload.open_gap_count,
        )
        return payload

    @router.get("/providers", response_model=MarketDataProvidersResponse)
    async def market_data_providers(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> MarketDataProvidersResponse:
        return await _svc(conn, settings).list_providers()

    @router.get("/gaps", response_model=MarketDataGapListResponse)
    async def market_data_gaps(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> MarketDataGapListResponse:
        return await _svc(conn, settings).list_gaps(limit=limit)

    @router.post("/gaps/{gap_id}/resolve", response_model=MarketDataGapResolveResponse)
    @limiter.limit("10/minute")
    async def market_data_gap_resolve(
        request: Request,  # noqa: ARG001
        gap_id: int,
        body: MarketDataGapResolveRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> MarketDataGapResolveResponse:
        require_dangerous_confirm(body, x_confirm)
        try:
            return await _svc(conn, settings).resolve_gap(
                gap_id,
                actor=actor_from_user(user),
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @router.post("/backfill", response_model=MarketBackfillResponse)
    @limiter.limit("5/minute")
    async def market_data_backfill(
        request: Request,  # noqa: ARG001
        body: MarketBackfillRequest,
        user: MasterAdminUser,
        conn: DbConn,
        settings: SettingsDep,
        x_confirm: str | None = Header(default=None, alias="X-Confirm"),
    ) -> MarketBackfillResponse:
        require_dangerous_confirm(body, x_confirm)
        return await _svc(conn, settings).backfill(body, actor=actor_from_user(user))

    @router.get("/universe", response_model=MarketUniverseResponse)
    async def market_data_universe(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
    ) -> MarketUniverseResponse:
        return await _svc(conn, settings).get_universe()

    @router.get("/market-cap-events", response_model=MarketCapEventsResponse)
    async def market_data_cap_events(
        user: CurrentUser,
        conn: DbConn,
        settings: SettingsDep,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> MarketCapEventsResponse:
        return await _svc(conn, settings).market_cap_events(limit=limit)

    return router
