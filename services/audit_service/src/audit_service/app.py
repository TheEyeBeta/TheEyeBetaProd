# STATUS: scaffolded, not deployed. Pending: deploy verify API (chain now written by BaseWorker).
"""FastAPI application for audit verification and service lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from audit_service.chain import verify_range
from audit_service.consumer import AuditEventConsumer
from audit_service.export import schedule_nightly_export
from audit_service.metrics import AuditMetrics
from audit_service.models import VerifyResponse
from audit_service.settings import Settings

log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the audit-service FastAPI application."""
    cfg = settings or Settings()
    metrics = AuditMetrics()
    consumer = AuditEventConsumer(cfg, metrics)
    scheduler = AsyncIOScheduler(timezone="UTC")
    schedule_nightly_export(cfg, scheduler)
    consumer_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal consumer_task
        try:
            await consumer.start()
            consumer_task = asyncio.create_task(consumer.run_forever())
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_nats_consumer_unavailable", error=str(exc))
        scheduler.start()
        log.info("audit_service_started", host=cfg.host, port=cfg.port)
        yield
        scheduler.shutdown(wait=False)
        if consumer_task is not None:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
        await consumer.stop()
        log.info("audit_service_stopped")

    app = FastAPI(title="audit-service", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        """Prometheus scrape endpoint."""
        await metrics.refresh_from_db(cfg.pg_dsn())
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)

    @app.get("/audit/verify", response_model=VerifyResponse)
    async def verify_audit(
        from_ts: datetime = Query(..., alias="from"),
        to_ts: datetime = Query(..., alias="to"),
    ) -> VerifyResponse:
        """Recompute the hash chain for rows in ``[from, to]`` and report integrity."""
        if to_ts < from_ts:
            raise HTTPException(status_code=400, detail="'to' must be >= 'from'")
        result = await verify_range(cfg.pg_dsn(), from_ts=from_ts, to_ts=to_ts)
        return VerifyResponse(
            status=result.status,
            rows_checked=result.rows_checked,
            first_bad_row_id=result.first_bad_row_id,
            detail=result.detail,
        )

    return app
