"""Background jobs for master-orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog

from master_orchestrator.clients import RiskServiceClient

if TYPE_CHECKING:
    from master_orchestrator.settings import Settings

log = structlog.get_logger()


class RiskMetricsScheduler:
    """Recompute portfolio risk metrics on a fixed interval."""

    # TODO(#4): theeyebeta.risk_metrics is an empty hypertable with no active writer.
    # This scheduler is the intended writer path (via RiskServiceClient), but it only runs
    # when settings.risk_service_url is set; risk_service is scaffolded and NOT deployed
    # (see SERVICES_STATUS.md), so start() takes the skip branch and risk_metrics stays
    # empty. Do not start the scaffolded service ad hoc — deploy it properly. Tracked in #4.

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = RiskServiceClient(settings.risk_service_url)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def _portfolio_ids(self) -> list[str]:
        raw = self._settings.risk_metrics_portfolio_ids.strip()
        if raw:
            return [p.strip() for p in raw.split(",") if p.strip()]
        if self._settings.default_portfolio_id:
            return [self._settings.default_portfolio_id]
        return []

    async def _loop(self) -> None:
        interval = self._settings.risk_metrics_interval_seconds
        while not self._stop.is_set():
            for portfolio_id in self._portfolio_ids():
                try:
                    await self._client.compute_portfolio_metrics(portfolio_id)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "risk_metrics_recompute_failed",
                        portfolio_id=portfolio_id,
                        error=str(exc),
                    )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def start(self) -> None:
        """Start the background scheduler when risk-service is configured."""
        if not self._settings.risk_service_url or not self._portfolio_ids():
            log.debug("risk_metrics_scheduler_skipped")
            return
        self._task = asyncio.create_task(self._loop(), name="risk-metrics-scheduler")
        log.info(
            "risk_metrics_scheduler_started",
            interval_seconds=self._settings.risk_metrics_interval_seconds,
            portfolios=len(self._portfolio_ids()),
        )

    async def stop(self) -> None:
        """Stop the background scheduler."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
