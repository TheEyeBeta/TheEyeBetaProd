"""FastAPI status app and APScheduler jobs for rnd-agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from rnd_agent.email_digest import send_pending_digest
from rnd_agent.probe import ReadonlyRoleProbeError, verify_readonly_role
from rnd_agent.runner import RNDRunner
from rnd_agent.settings import Settings

log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build rnd-agent FastAPI application."""
    cfg = settings or Settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    runner = RNDRunner(cfg)

    async def _nightly_run() -> None:
        try:
            await runner.run()
        except Exception as exc:  # noqa: BLE001
            log.error("rnd_scheduled_run_failed", error=str(exc))

    async def _digest() -> None:
        try:
            await send_pending_digest(cfg)
        except Exception as exc:  # noqa: BLE001
            log.error("rnd_digest_failed", error=str(exc))

    scheduler.add_job(
        _nightly_run,
        trigger=CronTrigger(
            hour=cfg.run_cron_hour,
            minute=cfg.run_cron_minute,
            timezone="UTC",
        ),
        id="rnd_nightly_run",
        replace_existing=True,
    )
    scheduler.add_job(
        _digest,
        trigger=CronTrigger(
            hour=cfg.digest_cron_hour,
            minute=cfg.digest_cron_minute,
            timezone="UTC",
        ),
        id="rnd_pending_digest",
        replace_existing=True,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            verify_readonly_role(cfg.pg_dsn())
        except ReadonlyRoleProbeError:
            log.exception("rnd_readonly_probe_failed_aborting_startup")
            raise
        scheduler.start()
        log.info("rnd_agent_started", host=cfg.host, port=cfg.port)
        yield
        scheduler.shutdown(wait=False)
        log.info("rnd_agent_stopped")

    app = FastAPI(title="rnd-agent", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": cfg.service_name}

    @app.get("/status")
    async def status() -> dict[str, str | int | bool]:
        """Read-only service status for operators."""
        return {
            "service": cfg.service_name,
            "time_utc": datetime.now(tz=UTC).isoformat(),
            "dry_run": cfg.dry_run,
            "run_cron_utc": f"{cfg.run_cron_hour:02d}:{cfg.run_cron_minute:02d}",
            "digest_cron_utc": f"{cfg.digest_cron_hour:02d}:{cfg.digest_cron_minute:02d}",
        }

    @app.post("/run/trigger")
    async def trigger_run() -> dict[str, str]:
        """Manual trigger for operators (still respects dry_run)."""
        result = await runner.run()
        return {
            "run_id": str(result.run_id),
            "guard_outcome": result.guard_outcome,
            "proposals": str(len(result.proposal_ids)),
        }

    return app
