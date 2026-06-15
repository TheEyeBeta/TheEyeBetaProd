# STATUS: scaffolded, not deployed. Pending: deploy unit; gates risk_metrics (#4).
"""FastAPI entrypoint for master-orchestrator (port 7050)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
from uuid import UUID

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
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
    date: date | None = Field(default=None, description="Trading date for idempotency key")


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

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "service": settings.service_name, "version": settings.version}

    @app.post("/workflows/market-trio", response_model=WorkflowResult)
    async def run_market_trio(body: MarketTrioRequest) -> WorkflowResult:
        """Run market-trio workflow synchronously (testing/backfill)."""
        workflow = MarketTrioWorkflow(settings)
        try:
            return await workflow.run(body.market, body.snapshot_id, trade_date=body.date)
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
