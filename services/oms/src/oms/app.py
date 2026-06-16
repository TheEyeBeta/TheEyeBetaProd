"""FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID

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

from oms.audit import insert_audit_log
from oms.consumer import OmsEventConsumer
from oms.db import fetch_order_row
from oms.reconciliation import ReconciliationLoop
from oms.settings import Settings
from oms.state import OrderManager
from oms.submission_gate import PauseSource, SubmissionGate

log = structlog.get_logger()


class ApproveBody(BaseModel):
    """Optional operator metadata for approval."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(default="operator")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the OMS FastAPI application."""
    cfg = settings or Settings()
    manager = OrderManager(cfg.pg_dsn())
    gate = SubmissionGate(cfg.redis_url or None)
    consumer = OmsEventConsumer(cfg.nats_url, manager, gate)
    reconciliation = ReconciliationLoop(
        cfg.pg_dsn(),
        cfg.broker_adapter_url,
        cfg.nats_url,
        gate,
        interval_seconds=cfg.reconciliation_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            await consumer.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_nats_consumer_unavailable", error=str(exc))
        try:
            await reconciliation.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("oms_reconciliation_unavailable", error=str(exc))
        log.info("oms_started", host=cfg.host, port=cfg.port)
        yield
        await reconciliation.stop()
        await consumer.stop()
        await gate.aclose()
        log.info("oms_stopped")

    app = FastAPI(title="oms", version="0.1.0", lifespan=lifespan)
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
        lambda: float(consumer.inflight_tasks)
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
    async def health() -> dict[str, object]:
        paused = await gate.is_paused()
        return {
            "status": "ok",
            "service": cfg.service_name,
            "submissions_paused": paused,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/oms/reconciliation/resolve")
    async def resolve_reconciliation() -> dict[str, str]:
        """Manually clear reconciliation pause after drift is fixed."""
        await gate.resume(source=PauseSource.RECONCILIATION)
        return {"status": "resumed"}

    @app.post("/oms/orders/{order_id}/approve")
    async def approve_order(order_id: UUID, body: ApproveBody | None = None) -> dict[str, object]:
        """Approve a pending order, submit it, and notify the broker adapter."""
        if await gate.is_paused():
            raise HTTPException(
                status_code=423,
                detail="submissions paused pending reconciliation resolution",
            )
        approved_by = (body or ApproveBody()).approved_by
        try:
            row = await fetch_order_row(cfg.pg_dsn(), str(order_id))
            snapshots = await manager.approve(str(order_id), approved_by=approved_by)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not snapshots or not snapshots[0].ok:
            detail = snapshots[0].error if snapshots else "approve failed"
            raise HTTPException(status_code=409, detail=detail)

        await insert_audit_log(
            cfg.pg_dsn(),
            actor=approved_by,
            action="order.approve",
            entity_type="order",
            entity_id=str(order_id),
            payload={
                "portfolio_id": row["portfolio_id"],
                "transitions": [snap.status for snap in snapshots],
            },
        )

        payload = {
            "order_id": str(order_id),
            "portfolio_id": row["portfolio_id"],
            "instrument_id": row["instrument_id"],
            "side": row["side"],
            "qty": row["qty"],
            "status": snapshots[-1].status,
            "approved_by": approved_by,
        }
        if snapshots[-1].ok:
            try:
                await consumer.publish_approved(str(order_id), payload)
            except Exception as exc:  # noqa: BLE001
                log.warning("oms_approved_publish_failed", order_id=str(order_id), error=str(exc))

        return {
            "order_id": str(order_id),
            "status": snapshots[-1].status,
            "transitions": [
                {"status": snap.status, "ok": snap.ok, "error": snap.error} for snap in snapshots
            ],
        }

    return app
