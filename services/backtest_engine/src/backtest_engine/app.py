# STATUS: scaffolded, not deployed. Pending: deploy unit + data/snapshot wiring.
"""FastAPI application for the backtest engine."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backtest_engine.db import fetch_run_results, fetch_run_status
from backtest_engine.runner import BacktestRunner, RunConfig
from backtest_engine.settings import Settings

log = structlog.get_logger()


class RunBacktestBody(BaseModel):
    """POST /backtest/run request body."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    start_date: date
    end_date: date
    universe: str | None = None
    walk_forward: bool | None = None
    mode: str | None = Field(default=None, description="replay or redecision")
    config: dict[str, Any] = Field(default_factory=dict)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the backtest FastAPI application."""
    cfg = settings or Settings()
    runner = BacktestRunner(cfg)

    app = FastAPI(title=cfg.service_name, version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": cfg.service_name}

    @app.post("/backtest/run")
    async def run_backtest(body: RunBacktestBody, background: BackgroundTasks) -> dict[str, str]:
        """Enqueue an async backtest; poll status via GET /backtest/{id}/status."""
        if body.start_date > body.end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        config = RunConfig(
            strategy_id=body.strategy_id,
            start_date=body.start_date,
            end_date=body.end_date,
            universe=body.universe,
            walk_forward=body.walk_forward,
            mode=body.mode,
            config=body.config,
        )

        dsn = cfg.pg_dsn()
        from backtest_engine.db import insert_backtest_run  # noqa: PLC0415

        run_id = await insert_backtest_run(
            dsn,
            strategy_id=config.strategy_id,
            start_date=config.start_date,
            end_date=config.end_date,
            universe=config.universe or "",
            config={
                **config.config,
                "walk_forward": config.walk_forward,
                "mode": config.mode,
            },
            git_sha=cfg.git_sha,
        )

        async def _execute() -> None:
            try:
                await runner.run(
                    RunConfig(
                        strategy_id=config.strategy_id,
                        start_date=config.start_date,
                        end_date=config.end_date,
                        universe=config.universe,
                        walk_forward=config.walk_forward,
                        mode=config.mode,
                        config=config.config,
                        run_id=run_id,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("background_backtest_failed", run_id=str(run_id), error=str(exc))

        background.add_task(_execute)
        return {"backtest_run_id": str(run_id), "status": "running"}

    @app.get("/backtest/{run_id}/status")
    async def backtest_status(run_id: UUID) -> dict[str, Any]:
        """Return run status."""
        row = await fetch_run_status(cfg.pg_dsn(), run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="backtest run not found")
        return row

    @app.get("/backtest/{run_id}/results")
    async def backtest_results(run_id: UUID) -> dict[str, Any]:
        """Return metrics and result blob URI."""
        row = await fetch_run_results(cfg.pg_dsn(), run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="backtest run not found")
        if row["status"] != "succeeded":
            raise HTTPException(
                status_code=409,
                detail=f"backtest not complete (status={row['status']})",
            )
        return row

    return app
