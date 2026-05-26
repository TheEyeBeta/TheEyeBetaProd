"""FastAPI entrypoint for snapshot-packager (port 7011)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache

import asyncpg
import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from snapshot_packager.consumer import SnapshotPackagerService, database_url
from snapshot_packager.package import PackageResult, package_snapshot
from snapshot_packager.settings import Settings
from starlette.responses import Response

load_dotenv()

log = structlog.get_logger()
_consumer: SnapshotPackagerService | None = None
_consumer_task: asyncio.Task[None] | None = None
_pool: asyncpg.Pool | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


class SnapshotBuildRequest(BaseModel):
    """Request body for on-demand snapshot packaging."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    market: str = Field(description="Aggregated market code: US, HK, JP, TW, CN")
    trading_date: date = Field(alias="date", description="Trading calendar date")


class SnapshotBuildResponse(BaseModel):
    """Response from POST /snapshots/build."""

    model_config = ConfigDict(extra="forbid")

    market: str
    date: str
    snapshot_id: str
    blob_uri: str
    sha256: str
    universe_size: int


def _to_response(result: PackageResult) -> SnapshotBuildResponse:
    return SnapshotBuildResponse(
        market=result.market,
        date=result.trade_date.isoformat(),
        snapshot_id=str(result.snapshot_id),
        blob_uri=result.blob_uri,
        sha256=result.sha256_hex,
        universe_size=result.universe_size,
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start shared pool + NATS consumer on startup."""
    global _consumer, _consumer_task, _pool  # noqa: PLW0603

    _pool = await asyncpg.create_pool(database_url(), min_size=1, max_size=10)
    _consumer = SnapshotPackagerService(pool=_pool)
    await _consumer.start()
    _consumer_task = asyncio.create_task(_consumer.run_forever())
    log.info("snapshot_packager_started")
    yield
    if _consumer_task is not None:
        _consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _consumer_task
        _consumer_task = None
    if _consumer is not None:
        await _consumer.stop()
        _consumer = None
    if _pool is not None:
        await _pool.close()
        _pool = None
    log.info("snapshot_packager_stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="snapshot-packager",
        version=settings.version,
        lifespan=_lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "service": settings.service_name, "version": settings.version}

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/snapshots/build", response_model=SnapshotBuildResponse)
    async def build_snapshot_endpoint(body: SnapshotBuildRequest) -> SnapshotBuildResponse:
        """Build and persist a packaged snapshot (bypasses NATS; for backfill CLI)."""
        if _pool is None:
            raise HTTPException(status_code=503, detail="Database pool not ready")
        try:
            result = await package_snapshot(
                _pool,
                body.market,
                body.trading_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.error("snapshot_build_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return _to_response(result)

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
