"""FastAPI entrypoint for admin-service (port 7200, Tailscale + Cloudflare)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
import uvicorn
from api.agents import register_agents_routes
from api.agents import router as agents_router
from api.alerts import register_alerts_routes
from api.alerts import router as alerts_router
from api.audit import register_audit_routes
from api.audit import router as audit_router
from api.backtest import register_backtest_routes
from api.backtest import router as backtest_router
from api.costs import register_costs_routes
from api.costs import router as costs_router
from api.events import register_events_routes, start_nats_event_bridge
from api.events import router as events_router
from api.guard import register_guard_routes
from api.guard import router as guard_router
from api.ops import register_ops_routes
from api.ops import router as ops_router
from api.orders import register_orders_routes
from api.orders import router as orders_router
from api.prelive import register_prelive_routes
from api.prelive import router as prelive_router
from api.proposals import register_proposals_routes
from api.proposals import router as proposals_router
from api.services import register_services_routes
from api.services import router as services_router
from api.sql import register_sql_routes
from api.sql import router as sql_router
from api.timers import register_timers_routes
from api.timers import router as timers_router
from api.trading import register_trading_routes
from api.trading import router as trading_router
from api.trask import register_trask_routes
from api.trask import router as trask_router
from api.views import register_views_routes
from api.views import router as views_router
from api.workers import register_workers_routes
from api.workers import router as workers_router
from auth import register_auth_routes
from auth import router as auth_router
from deps import bind_app_state, close_resources, init_resources
from dotenv import load_dotenv
from errors import register_error_handlers
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from lib.event_broadcaster import EventBroadcaster
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
register_ops_routes()
register_workers_routes(limiter)
register_trask_routes(limiter)
register_alerts_routes(limiter)
register_prelive_routes()
register_trading_routes(limiter)
register_timers_routes(limiter)
register_events_routes()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the admin-service FastAPI application."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_resources(cfg)
        bind_app_state(app, cfg)
        app.state.event_broadcaster = EventBroadcaster()
        await start_nats_event_bridge(app)
        log.info("admin_service_started", host=cfg.host, port=cfg.port)
        yield
        drain = getattr(app.state, "_nats_event_drain", None)
        if drain is not None:
            await drain()
        await close_resources()
        log.info("admin_service_stopped")

    app = FastAPI(
        title="admin-service",
        version="0.3.0",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Propagate X-Request-ID through request lifecycle."""
        correlation_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response

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
    app.include_router(ops_router, prefix="/admin")
    app.include_router(workers_router, prefix="/admin")
    app.include_router(trask_router, prefix="/admin")
    app.include_router(alerts_router, prefix="/admin")
    app.include_router(prelive_router, prefix="/admin")
    app.include_router(trading_router, prefix="/admin")
    app.include_router(timers_router, prefix="/admin")
    app.include_router(events_router, prefix="/admin")

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
