# STATUS: deployed via theeye-master-orchestrator.service.
"""FastAPI entrypoint for master-orchestrator (port 7050)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from uuid import UUID

import structlog
from dotenv import load_dotenv
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

from master_orchestrator.consumer import SnapshotEventConsumer
from master_orchestrator.models import WorkflowResult
from master_orchestrator.scheduler import RiskMetricsScheduler
from master_orchestrator.settings import Settings
from master_orchestrator.workflow import MarketTrioWorkflow

load_dotenv()

log = structlog.get_logger()
_consumer: SnapshotEventConsumer | None = None
_risk_scheduler: RiskMetricsScheduler | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()


class MarketTrioRequest(BaseModel):
    """Manual workflow trigger body."""

    model_config = ConfigDict(extra="forbid")

    market: str
    snapshot_id: UUID
    trade_date: date | None = Field(
        default=None,
        description="Trading date for idempotency key",
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start NATS consumer on startup."""
    global _consumer, _risk_scheduler  # noqa: PLW0603
    settings = get_settings()
    _consumer = SnapshotEventConsumer(settings)
    try:
        await _consumer.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("mo_nats_consumer_unavailable", error=str(exc))
        _consumer = None
    _risk_scheduler = RiskMetricsScheduler(settings)
    await _risk_scheduler.start()
    log.info("master_orchestrator_started", port=settings.port)
    yield
    if _risk_scheduler is not None:
        await _risk_scheduler.stop()
        _risk_scheduler = None
    if _consumer is not None:
        await _consumer.stop()
        _consumer = None
    log.info("master_orchestrator_stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="master-orchestrator",
        version=settings.version,
        lifespan=_lifespan,
    )
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
    service_info.labels(service=settings.service_name).set(1)

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
            request_count.labels(settings.service_name, request.method, path, status).inc()
            request_latency.labels(settings.service_name, request.method, path).observe(
                time.perf_counter() - started,
            )
            if failed or status.startswith("5"):
                request_errors.labels(settings.service_name, request.method, path).inc()

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus scrape endpoint."""
        depth = _consumer.inflight_tasks if _consumer is not None else 0
        queue_depth.labels(service=settings.service_name).set(depth)
        return Response(
            content=generate_latest() + generate_latest(registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "service": settings.service_name, "version": settings.version}

    @app.post("/workflows/market-trio", response_model=WorkflowResult)
    async def run_market_trio(body: MarketTrioRequest) -> WorkflowResult:
        """Run market-trio workflow synchronously (testing/backfill)."""
        workflow = MarketTrioWorkflow(settings)
        try:
            return await workflow.run(body.market, body.snapshot_id, trade_date=body.trade_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.error("market_trio_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    """Run uvicorn when executed as a module."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        factory=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
