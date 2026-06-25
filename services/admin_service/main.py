"""FastAPI entrypoint for admin-service (port 7200, Tailscale + Cloudflare)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn
from api.agents import register_agents_routes
from api.agents import router as agents_router
from api.audit import register_audit_routes
from api.audit import router as audit_router
from api.backtest import register_backtest_routes
from api.backtest import router as backtest_router
from api.costs import register_costs_routes
from api.costs import router as costs_router
from api.guard import register_guard_routes
from api.guard import router as guard_router
from api.orders import register_orders_routes
from api.orders import router as orders_router
from api.proposals import register_proposals_routes
from api.proposals import router as proposals_router
from api.services import register_services_routes
from api.services import router as services_router
from api.sql import register_sql_routes
from api.sql import router as sql_router
from api.cloudflare import register_cloudflare_routes
from api.cloudflare import router as cloudflare_router
from api.edge import register_edge_routes
from api.edge import router as edge_router
from api.edge_views import register_edge_views
from api.edge_views import router as edge_views_router
from api.master_admin import register_master_admin_routes
from api.master_admin import router as master_admin_router
from api.module_views import register_module_views
from api.module_views import router as module_views_router
from api.users import register_users_routes
from api.users import router as users_router
from api.workers import register_workers_routes
from api.workers import router as workers_router
from api.timers import register_timers_routes
from api.timers import router as timers_router
from api.terminal_data import register_terminal_data_routes
from api.terminal_data import router as terminal_data_router
from api.trading import emergency_router as emergency_views_router
from api.trading import register_trading_routes
from api.trading import router as trading_router
from api.risk import register_risk_routes
from api.risk import router as risk_router
from api.compliance import register_compliance_routes
from api.compliance import router as compliance_router
from api.broker import register_broker_routes
from api.broker import router as broker_router
from api.oms import register_oms_routes
from api.oms import router as oms_router
from api.market_data import register_market_data_routes
from api.market_data import router as market_data_router
from api.sectors import register_sectors_routes
from api.sectors import router as sectors_router
from api.universe import register_universe_routes
from api.universe import router as universe_router
from api.snapshots import register_snapshots_routes
from api.snapshots import router as snapshots_router
from api.pipelines import register_pipelines_routes
from api.pipelines import router as pipelines_router
from api.backtests import register_backtests_routes
from api.backtests import router as backtests_router
from api.reports import register_reports_routes
from api.reports import router as reports_router
from api.commands import console_router, register_commands_routes
from api.commands import router as commands_router
from api.views import register_views_routes
from api.views import router as views_router
from auth import register_auth_routes
from auth import router as auth_router
from deps import bind_app_state, close_resources, init_resources
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from settings import Settings, get_settings
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException
from web import mount_static, page_context, prefers_html, register_web_routes, templates
from web import router as web_router

load_dotenv()

log = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
register_auth_routes(limiter)
register_orders_routes(limiter)
register_audit_routes()
register_agents_routes(limiter)
register_guard_routes(limiter)
register_services_routes(limiter)
register_backtest_routes(limiter)
register_costs_routes()
register_sql_routes(limiter)
register_proposals_routes(limiter)
register_master_admin_routes()
register_cloudflare_routes(limiter)
register_edge_routes(limiter)
register_edge_views()
register_module_views()
register_users_routes(limiter)
register_workers_routes(limiter)
register_timers_routes(limiter)
register_terminal_data_routes(limiter)
register_trading_routes(limiter)
register_risk_routes(limiter)
register_compliance_routes(limiter)
register_broker_routes(limiter)
register_oms_routes(limiter)
register_market_data_routes(limiter)
register_sectors_routes()
register_universe_routes()
register_snapshots_routes(limiter)
register_pipelines_routes(limiter)
register_backtests_routes(limiter)
register_reports_routes(limiter)
register_commands_routes(limiter)
register_views_routes(limiter)
register_web_routes()

# Aliases for intuitive URL guesses that don't match the real page routes —
# 308s so operators bookmarking a logical path land on the canonical page
# instead of a raw 404.
_LEGACY_ADMIN_REDIRECTS: dict[str, str] = {
    "/admin/emergency-trading": "/admin/emergency",
    "/admin/oms": "/admin/orders",
    "/admin/portfolio": "/admin/broker",
    "/admin/database": "/admin/sql",
    "/admin/command-center": "/admin/terminal/",
}


def _redirect_to(canonical_path: str) -> Callable[[], Coroutine[Any, Any, RedirectResponse]]:
    """Build a GET handler that 308-redirects to ``canonical_path``."""

    async def _handler() -> RedirectResponse:
        return RedirectResponse(url=canonical_path, status_code=308)

    return _handler


# Placeholder routers for P-AD-02..05 (pages, API, ops) — mounted with /admin prefix.
pages_router = APIRouter(prefix="/pages", tags=["pages"])
api_router = APIRouter(prefix="/api", tags=["api"])
ops_router = APIRouter(prefix="/ops", tags=["ops"])


@pages_router.get("/")
async def pages_placeholder() -> dict[str, str]:
    """Dashboard placeholder until P-AD-02."""
    return {"status": "not_implemented", "phase": "P-AD-02"}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the admin-service FastAPI application."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_resources(cfg)
        bind_app_state(app, cfg)
        log.info("admin_service_started", host=cfg.host, port=cfg.port)
        yield
        await close_resources()
        log.info("admin_service_stopped")

    app = FastAPI(
        title="admin-service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )

    @app.get("/admin/health")
    @limiter.exempt
    async def health(request: Request) -> dict[str, str]:
        """Liveness probe for compose and load balancers."""
        return {"status": "ok", "service": cfg.service_name}

    app.include_router(auth_router, prefix="/admin/auth")
    # views_router holds the HTML pages + htmx fragments — mounted first so
    # paths like /admin/orders and /admin/orders/fragments/... resolve to the
    # page handlers instead of being parsed as parametric JSON routes
    # (``/admin/orders/{order_id}``).
    app.include_router(views_router, prefix="/admin")
    app.include_router(users_router, prefix="/admin")
    app.include_router(workers_router, prefix="/admin")
    app.include_router(timers_router, prefix="/admin")
    app.include_router(terminal_data_router, prefix="/admin")
    app.include_router(trading_router, prefix="/admin")
    app.include_router(emergency_views_router, prefix="/admin")
    app.include_router(risk_router, prefix="/admin")
    app.include_router(compliance_router, prefix="/admin")
    app.include_router(broker_router, prefix="/admin")
    app.include_router(oms_router, prefix="/admin")
    app.include_router(market_data_router, prefix="/admin")
    app.include_router(sectors_router, prefix="/admin")
    app.include_router(universe_router, prefix="/admin")
    app.include_router(snapshots_router, prefix="/admin")
    app.include_router(pipelines_router, prefix="/admin")
    app.include_router(backtests_router, prefix="/admin")
    app.include_router(reports_router, prefix="/admin")
    app.include_router(commands_router, prefix="/admin")
    app.include_router(console_router, prefix="/admin")
    app.include_router(module_views_router, prefix="/admin")
    app.include_router(orders_router, prefix="/admin")
    app.include_router(audit_router, prefix="/admin")
    app.include_router(agents_router, prefix="/admin")
    app.include_router(guard_router, prefix="/admin")
    app.include_router(services_router, prefix="/admin")
    app.include_router(backtest_router, prefix="/admin")
    app.include_router(costs_router, prefix="/admin")
    app.include_router(sql_router, prefix="/admin")
    app.include_router(proposals_router, prefix="/admin")
    app.include_router(master_admin_router, prefix="/admin")
    app.include_router(cloudflare_router, prefix="/admin")
    app.include_router(edge_router, prefix="/admin")
    app.include_router(edge_views_router, prefix="/admin")
    app.include_router(web_router, prefix="/admin")
    app.include_router(pages_router, prefix="/admin")
    app.include_router(api_router, prefix="/admin")
    app.include_router(ops_router, prefix="/admin")

    for legacy_path, canonical_path in _LEGACY_ADMIN_REDIRECTS.items():
        app.add_api_route(
            legacy_path,
            _redirect_to(canonical_path),
            methods=["GET"],
            include_in_schema=False,
        )

    @app.exception_handler(StarletteHTTPException)
    async def admin_404_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> Response:
        """Render a styled 404 page for browser/htmx navigation; JSON for API clients."""
        if exc.status_code == 404 and prefers_html(request):
            return templates.TemplateResponse(
                request,
                "pages/error_404.html",
                page_context(request, title="Not found"),
                status_code=404,
            )
        return await http_exception_handler(request, exc)

    mount_static(app)

    return app


app = create_app()


def main() -> None:
    """Run uvicorn bound to all interfaces on port 7200."""
    cfg = get_settings()
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        factory=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
