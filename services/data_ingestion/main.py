# STATUS: scaffolded; not deployed as a service (prices/macro/news run via standalone timers).
"""FastAPI entrypoint for the data-ingestion service.

Exposes health/metrics endpoints, admin-triggered ingest runs, and a daily
APScheduler cron that aligns with major market close times (UTC).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any, Literal

import bcrypt
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

log = structlog.get_logger()
security = HTTPBasic()

_SCHEDULE_UTC = (
    (0, 30),
    (6, 30),
    (22, 30),
)


class Settings(BaseSettings):
    """Service configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "data-ingestion"
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = 7010
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password_bcrypt: str = Field(
        default="",
        validation_alias="ADMIN_PASSWORD_BCRYPT",
    )


class IngestRunRequest(BaseModel):
    """Optional parameters for a manual ingest run."""

    model_config = ConfigDict(extra="forbid")

    adapter: str | None = Field(
        default=None,
        description="Adapter to run: yfinance, fred, prices, macro, or all (default).",
    )
    market: str | None = Field(
        default=None,
        description="Exchange/market code filter (reserved; not yet applied).",
    )
    trading_date: date | None = Field(
        default=None,
        alias="date",
        description="Target trading date (default: today UTC).",
    )


class MetricsState(BaseModel):
    """In-process counters exposed at GET /metrics."""

    model_config = ConfigDict(frozen=True)

    scheduler_running: bool = False
    scheduled_jobs: int = 0
    ingest_runs_total: int = 0
    ingest_runs_failed: int = 0
    last_ingest_at: datetime | None = None
    last_ingest_status: Literal["ok", "error", "idle"] = "idle"
    last_ingest_detail: dict[str, Any] | None = None


_metrics = MetricsState()
_scheduler: AsyncIOScheduler | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


def _verify_admin(
    credentials: HTTPBasicCredentials,
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate HTTP Basic credentials against bcrypt-hashed admin password."""
    if not settings.admin_password_bcrypt:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth is not configured (ADMIN_PASSWORD_BCRYPT missing)",
        )
    if credentials.username != settings.admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    try:
        ok = bcrypt.checkpw(
            credentials.password.encode(),
            settings.admin_password_bcrypt.encode(),
        )
    except ValueError as exc:
        log.error("admin_bcrypt_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin auth misconfigured",
        ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def _resolve_adapter_names(adapter: str | None) -> list[str]:
    """Map request adapter string to canonical adapter names."""
    from data_ingestion.adapters import resolve_adapter_name  # noqa: PLC0415

    try:
        return resolve_adapter_name(adapter)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


async def _run_ingest(
    *,
    adapter_names: list[str],
    target_date: date,
    market: str | None,
    trigger: str,
) -> dict[str, Any]:
    """Execute selected ingestion pipelines and update metrics."""
    global _metrics  # noqa: PLW0603

    if market:
        log.info("ingest_market_filter_ignored", market=market, trigger=trigger)

    from data_ingestion.adapters import resolve_adapter_name  # noqa: PLC0415
    from data_ingestion.pipeline import (  # noqa: PLC0415
        IngestionPipeline,
        run_adapter,
    )

    results: dict[str, Any] = {"trigger": trigger, "date": str(target_date), "jobs": {}}
    failed = False

    full_run = set(adapter_names) == set(resolve_adapter_name(None))
    try:
        if full_run:
            results["jobs"]["pipeline"] = await IngestionPipeline().run(target_date)
        else:
            for name in adapter_names:
                results["jobs"][name] = await run_adapter(name, target_date)
    except Exception as exc:  # noqa: BLE001
        failed = True
        results["jobs"]["error"] = str(exc)
        log.error("ingest_run_failed", trigger=trigger, error=str(exc))

    now = datetime.now(tz=UTC)
    _metrics = _metrics.model_copy(
        update={
            "ingest_runs_total": _metrics.ingest_runs_total + 1,
            "ingest_runs_failed": _metrics.ingest_runs_failed + (1 if failed else 0),
            "last_ingest_at": now,
            "last_ingest_status": "error" if failed else "ok",
            "last_ingest_detail": results,
        },
    )
    if failed:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=results,
        )
    return results


async def _scheduled_ingest() -> None:
    """Cron callback: run full daily ingest at market-close-aligned UTC times."""
    from data_ingestion.pipeline import DEFAULT_ADAPTER_NAMES  # noqa: PLC0415

    target = date.today()
    log.info("scheduled_ingest_start", date=str(target))
    try:
        await _run_ingest(
            adapter_names=list(DEFAULT_ADAPTER_NAMES),
            target_date=target,
            market=None,
            trigger="scheduler",
        )
    except HTTPException:
        log.error("scheduled_ingest_failed", date=str(target))
    except Exception as exc:  # noqa: BLE001
        log.error("scheduled_ingest_unexpected", date=str(target), error=str(exc))


def _start_scheduler() -> AsyncIOScheduler:
    """Create and start the AsyncIOScheduler with UTC cron triggers."""
    sched = AsyncIOScheduler(timezone=UTC)
    for hour, minute in _SCHEDULE_UTC:
        sched.add_job(
            _scheduled_ingest,
            CronTrigger(hour=hour, minute=minute, timezone=UTC),
            id=f"ingest-{hour:02d}{minute:02d}utc",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    sched.start()
    log.info(
        "scheduler_started",
        jobs=len(sched.get_jobs()),
        schedule_utc=[f"{h:02d}:{m:02d}" for h, m in _SCHEDULE_UTC],
    )
    return sched


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Start APScheduler on startup and shut it down cleanly."""
    global _metrics, _scheduler  # noqa: PLW0603

    from data_ingestion.writers.postgres_writer import close_pool, get_pool  # noqa: PLC0415

    await get_pool()
    _scheduler = _start_scheduler()
    _metrics = _metrics.model_copy(
        update={
            "scheduler_running": True,
            "scheduled_jobs": len(_scheduler.get_jobs()),
        },
    )
    yield
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    await close_pool()
    _metrics = _metrics.model_copy(update={"scheduler_running": False, "scheduled_jobs": 0})
    log.info("scheduler_stopped")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="data-ingestion",
        version=settings.version,
        lifespan=_lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe — always returns ok when the process is up."""
        return {"status": "ok", "service": settings.service_name, "version": settings.version}

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/metrics/state")
    async def metrics_state() -> MetricsState:
        """JSON ingestion state for debugging."""
        return _metrics

    @app.post("/ingest/run")
    async def ingest_run(
        _: None = Depends(_verify_admin),
        body: IngestRunRequest | None = None,
        adapter: str | None = Query(default=None, description="Adapter name or 'all'"),
        trading_date: date | None = Query(default=None, alias="date"),
    ) -> dict[str, Any]:
        """Trigger an on-demand ingest run (admin Basic auth required)."""
        merged_adapter = adapter if adapter is not None else (body.adapter if body else None)
        merged_date = trading_date or (body.trading_date if body else None)
        merged_market = body.market if body else None
        adapter_names = _resolve_adapter_names(merged_adapter)
        target = merged_date or date.today()
        return await _run_ingest(
            adapter_names=adapter_names,
            target_date=target,
            market=merged_market,
            trigger="api",
        )

    return app


app = create_app()


def main() -> None:
    """Run uvicorn when executed as ``python -m`` or via console script."""
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
