"""FastAPI entrypoint for admin-service (port 7200, Tailscale + Cloudflare)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from api.views import register_views_routes
from api.views import router as views_router
from auth import register_auth_routes
from auth import router as auth_router
from deps import bind_app_state, close_resources, init_resources
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from settings import Settings, get_settings
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from web import mount_static, register_web_routes
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
register_views_routes(limiter)
register_web_routes()

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
    app.include_router(orders_router, prefix="/admin")
    app.include_router(audit_router, prefix="/admin")
    app.include_router(agents_router, prefix="/admin")
    app.include_router(guard_router, prefix="/admin")
    app.include_router(services_router, prefix="/admin")
    app.include_router(backtest_router, prefix="/admin")
    app.include_router(costs_router, prefix="/admin")
    app.include_router(sql_router, prefix="/admin")
    app.include_router(proposals_router, prefix="/admin")
    app.include_router(web_router, prefix="/admin")
    app.include_router(pages_router, prefix="/admin")
    app.include_router(api_router, prefix="/admin")
    app.include_router(ops_router, prefix="/admin")

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
