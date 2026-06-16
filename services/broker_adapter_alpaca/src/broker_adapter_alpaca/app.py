"""FastAPI broker-adapter application."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from broker_adapter_alpaca.adapter import AlpacaAdapter
from broker_adapter_alpaca.consumer import ApprovedOrderConsumer
from broker_adapter_alpaca.live_gate import (
    DataGapBlockError,
    LiveTradingNotApprovedError,
    TradingDisabledError,
    assert_live_trading_allowed,
    assert_order_submission_allowed,
)
from broker_adapter_alpaca.settings import Settings
from broker_adapter_alpaca.streamer import TradeUpdateStreamer
from zinc_schemas.broker_base import SubmitOrderRequest

log = structlog.get_logger()


class MarketOrderBody(BaseModel):
    """Direct market order submission (e2e / ops)."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = ""
    symbol: str
    qty: float = Field(gt=0)
    side: str = "buy"
    account: str = "zinc"  # "zinc" | "nyse" | "nasdaq"


async def _enforce_startup_gates(cfg: Settings) -> None:
    """Refuse live mode without DB approval; require credentials."""
    if cfg.mode == "live":
        await assert_live_trading_allowed(cfg.pg_dsn())
    if not cfg.credentials_configured():
        log.warning("broker_adapter_credentials_missing")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build broker-adapter FastAPI app."""
    cfg = settings or Settings()
    adapter = AlpacaAdapter(cfg)
    consumer = ApprovedOrderConsumer(cfg, adapter)
    streamer = TradeUpdateStreamer(adapter, cfg.nats_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await _enforce_startup_gates(cfg)
        if cfg.credentials_configured():
            try:
                await streamer.start()
            except Exception as exc:  # noqa: BLE001
                log.warning("broker_adapter_streamer_unavailable", error=str(exc))
            try:
                await consumer.start()
            except Exception as exc:  # noqa: BLE001
                log.warning("broker_adapter_nats_unavailable", error=str(exc))
        log.info(
            "broker_adapter_started",
            host=cfg.host,
            port=cfg.port,
            mode=cfg.mode,
        )
        yield
        await consumer.stop()
        await streamer.stop()
        log.info("broker_adapter_stopped")

    app = FastAPI(title=cfg.service_name, version="0.2.0", lifespan=lifespan)
    registry = CollectorRegistry()
    request_count = Counter(
        "theeye_http_request_count_total",
        "HTTP requests handled by TheEye services",
        ("service", "method", "path", "status"),
        registry=registry,
    )
    request_latency = Histogram(
        "theeye_http_request_latency_seconds",
        "HTTP request latency for TheEye services",
        ("service", "method", "path"),
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=registry,
    )
    request_errors = Counter(
        "theeye_http_request_errors_total",
        "HTTP 5xx responses and unhandled exceptions in TheEye services",
        ("service", "method", "path"),
        registry=registry,
    )
    queue_depth = Gauge(
        "theeye_queue_depth",
        "In-process async work queue depth by service",
        ("service",),
        registry=registry,
    )
    service_info = Gauge(
        "theeye_service_info",
        "Static service identity for TheEye services",
        ("service",),
        registry=registry,
    )
    queue_depth.labels(service=cfg.service_name).set_function(
        lambda: float(consumer.inflight_tasks),
    )
    service_info.labels(service=cfg.service_name).set(1)

    @app.middleware("http")
    async def prometheus_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        started = time.perf_counter()
        status = "500"
        failed = False
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        except Exception:
            failed = True
            raise
        finally:
            route = request.scope.get("route")
            path = str(getattr(route, "path", request.url.path))
            request_count.labels(cfg.service_name, request.method, path, status).inc()
            request_latency.labels(cfg.service_name, request.method, path).observe(
                time.perf_counter() - started,
            )
            if failed or status.startswith("5"):
                request_errors.labels(cfg.service_name, request.method, path).inc()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": cfg.service_name,
            "mode": cfg.mode,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/positions")
    async def list_positions(account: str = "zinc") -> dict[str, object]:
        """List Alpaca positions for one sub-account (?account=zinc|nyse|nasdaq)."""
        if not cfg.credentials_configured():
            raise HTTPException(status_code=503, detail="Alpaca credentials not configured")
        return {"account": account, "positions": adapter.list_positions(account)}

    @app.get("/v1/positions/all")
    async def list_all_positions() -> dict[str, object]:
        """List Alpaca positions across all three sub-accounts."""
        if not cfg.credentials_configured():
            raise HTTPException(status_code=503, detail="Alpaca credentials not configured")
        return {"positions": adapter.list_all_positions()}

    @app.get("/v1/orders")
    async def list_orders(account: str = "zinc") -> dict[str, object]:
        """List recent Alpaca orders for one sub-account (?account=zinc|nyse|nasdaq)."""
        if not cfg.credentials_configured():
            raise HTTPException(status_code=503, detail="Alpaca credentials not configured")
        return {"account": account, "orders": adapter.list_orders(account)}

    @app.post("/v1/orders/market")
    async def submit_market(body: MarketOrderBody) -> dict[str, object]:
        """Submit a market order directly to Alpaca (e2e)."""
        if not cfg.credentials_configured():
            raise HTTPException(status_code=503, detail="Alpaca credentials not configured")
        if cfg.mode == "live":
            try:
                await assert_order_submission_allowed(
                    cfg.pg_dsn(),
                    live_mode=True,
                    redis_url=cfg.redis_url or None,
                )
            except (LiveTradingNotApprovedError, DataGapBlockError, TradingDisabledError) as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        else:
            try:
                await assert_order_submission_allowed(cfg.pg_dsn(), live_mode=False)
            except DataGapBlockError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        order_id = body.order_id or body.symbol
        request = SubmitOrderRequest(
            order_id=order_id,
            symbol=body.symbol,
            qty=body.qty,
            side=body.side,
            account=body.account,
        )
        import asyncio

        result = await asyncio.to_thread(adapter.submit_order, request)
        return {"order": result.model_dump()}

    return app
