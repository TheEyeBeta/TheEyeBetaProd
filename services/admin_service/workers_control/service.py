"""Workers / Schedulers control plane orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from audit_log import write_audit_log
from settings import Settings
from workers_control.registry import (
    CANONICAL_TIMERS,
    CANONICAL_WORKERS,
    ControlGap,
    TimerDefinition,
    WorkerDefinition,
    timer_by_key,
    worker_by_key,
)
from workers_control.repository import WorkersRepository
from workers_control.systemd_probe import SystemdProbe, SystemdResult
from zinc_schemas.admin_dto import (
    TimerActionResponse,
    TimerDetailResponse,
    TimerJournalEntry,
    TimerJournalResponse,
    TimerListResponse,
    TimerRegistryEntry,
    TimerSchedulePatchRequest,
    WorkerActionResponse,
    WorkerConfigPatchRequest,
    WorkerConfigResponse,
    WorkerControlGap,
    WorkerDetailResponse,
    WorkerListResponse,
    WorkerLogEntry,
    WorkerLogsResponse,
    WorkerRegistryEntry,
    WorkerRunEntry,
    WorkerRunListResponse,
)

log = structlog.get_logger()


class WorkersControlService:
    """Registry visibility, audit-backed status, and guarded mutations."""

    def __init__(
        self,
        conn: Any,
        settings: Settings,
        *,
        systemd: SystemdProbe | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = WorkersRepository(conn)
        self._systemd = systemd or SystemdProbe(
            enabled=settings.workers_systemd_enabled(),
        )

    @property
    def mode(self) -> str:
        if self._settings.workers_uses_local_mode():
            return "local"
        if self._systemd.available:
            return "live"
        return "local"

    def _gap_dtos(self, gaps: tuple[ControlGap, ...]) -> list[WorkerControlGap]:
        resolved: list[WorkerControlGap] = [
            WorkerControlGap(action=g.action, reason=g.reason) for g in gaps
        ]
        if not self._systemd.available:
            if not any(g.action == "systemd" for g in gaps):
                resolved.append(
                    WorkerControlGap(
                        action="systemd",
                        reason="systemd control unavailable on this host (non-Linux or disabled).",
                    ),
                )
        return resolved

    @staticmethod
    def _run_entry(row: dict[str, Any] | None) -> WorkerRunEntry | None:
        if not row:
            return None
        return WorkerRunEntry(
            run_id=int(row["run_id"]),
            worker_name=str(row["worker_name"]),
            worker_type=str(row.get("worker_type") or ""),
            trade_date=row["trade_date"],
            run_type=str(row["run_type"]),
            status=str(row["status"]),
            started_at=row["started_at"],
            ended_at=row.get("ended_at"),
            duration_seconds=row.get("duration_seconds"),
            records_written=row.get("records_written"),
            records_expected=row.get("records_expected"),
            error_message=row.get("error_message"),
            error_class=row.get("error_class"),
        )

    def _health(
        self,
        *,
        last_run: WorkerRunEntry | None,
        heartbeat_at: datetime | None,
        heartbeat_status: str | None,
        paused: bool,
    ) -> str:
        if paused:
            return "degraded"
        stale_after = timedelta(seconds=self._settings.workers_heartbeat_stale_seconds)
        now = WorkersRepository.utc_now()
        if last_run and last_run.status == "FAILED":
            return "degraded"
        if heartbeat_at:
            hb = heartbeat_at if heartbeat_at.tzinfo else heartbeat_at.replace(tzinfo=UTC)
            if (now - hb) > stale_after:
                return "stale"
        if heartbeat_status in {"failed", "error"}:
            return "degraded"
        if last_run and last_run.status == "COMPLETED":
            return "healthy"
        if heartbeat_at:
            return "healthy"
        return "unknown"

    async def _build_worker_entry(
        self,
        worker: WorkerDefinition,
        *,
        last_runs: dict[str, dict[str, Any]],
        heartbeats: dict[str, dict[str, Any]],
        failures: dict[str, list[dict[str, Any]]],
        control_states: dict[str, dict[str, Any]],
        next_runs: dict[str, str | None],
    ) -> WorkerRegistryEntry:
        primary_name = worker.audit_worker_names[0] if worker.audit_worker_names else None
        last_row = None
        for name in worker.audit_worker_names:
            if name in last_runs:
                last_row = last_runs[name]
                break
        last_run = self._run_entry(last_row)
        hb_row = None
        for name in worker.audit_worker_names:
            if name in heartbeats:
                hb_row = heartbeats[name]
                break
        control = control_states.get(worker.key, {})
        paused = bool(control.get("paused"))
        heartbeat_at = hb_row["last_heartbeat"] if hb_row else None
        heartbeat_status = str(hb_row["status"]) if hb_row else None
        recent: list[WorkerRunEntry] = []
        for name in worker.audit_worker_names:
            for row in failures.get(name, []):
                entry = self._run_entry(row)
                if entry:
                    recent.append(entry)
        recent.sort(key=lambda r: r.started_at, reverse=True)
        gaps = self._gap_dtos(worker.control_gaps)
        if not worker.supports_stop:
            gaps.append(
                WorkerControlGap(action="stop", reason="Stop is not supported for this worker."),
            )
        if not worker.supports_pause:
            gaps.append(
                WorkerControlGap(action="pause", reason="Pause is not supported for this worker."),
            )
        return WorkerRegistryEntry(
            name=worker.key,
            title=worker.title,
            audit_worker_name=primary_name,
            audit_worker_names=list(worker.audit_worker_names),
            systemd_service=worker.systemd_service,
            timer_unit=worker.systemd_timer,
            schedule=str(control.get("schedule_override") or worker.schedule),
            priority=worker.priority,
            health=self._health(
                last_run=last_run,
                heartbeat_at=heartbeat_at,
                heartbeat_status=heartbeat_status,
                paused=paused,
            ),
            paused=paused,
            enabled=bool(control.get("enabled", True)),
            last_run=last_run,
            next_scheduled_run=next_runs.get(worker.key),
            heartbeat_at=heartbeat_at,
            heartbeat_status=heartbeat_status,
            recent_failures=recent[:5],
            control_gaps=gaps,
            supports_run=worker.supports_run,
            supports_stop=worker.supports_stop and self._systemd.can_control(worker.systemd_service),
            supports_pause=worker.supports_pause,
            supports_resume=worker.supports_pause,
            supports_retry=worker.supports_retry,
            supports_config=worker.supports_config,
            source_path=worker.source_path,
        )

    async def list_workers(self) -> WorkerListResponse:
        all_names = tuple(
            name for worker in CANONICAL_WORKERS for name in worker.audit_worker_names
        )
        all_ids = all_names
        control_states = await self._repo.list_control_states()
        last_runs = await self._repo.fetch_last_runs(all_names)
        heartbeats = await self._repo.fetch_heartbeats(all_ids)
        failures = await self._repo.fetch_recent_failures(all_names, limit=20)
        next_runs: dict[str, str | None] = {}
        for worker in CANONICAL_WORKERS:
            timer = worker.systemd_timer
            if timer and self._systemd.available:
                next_runs[worker.key] = await self._systemd.timer_next_elapsed(timer)
            else:
                next_runs[worker.key] = None
        workers = [
            await self._build_worker_entry(
                worker,
                last_runs=last_runs,
                heartbeats=heartbeats,
                failures=failures,
                control_states=control_states,
                next_runs=next_runs,
            )
            for worker in CANONICAL_WORKERS
        ]
        return WorkerListResponse(
            mode=self.mode,
            audit_tables_available=await self._repo.audit_tables_available(),
            workers=workers,
            checked_at=WorkersRepository.utc_now(),
        )

    async def get_worker(self, name: str) -> WorkerDetailResponse | None:
        worker = worker_by_key(name)
        if worker is None:
            return None
        listing = await self.list_workers()
        entry = next((row for row in listing.workers if row.name == name), None)
        if entry is None:
            return None
        runs = await self._repo.fetch_runs(worker.audit_worker_names, limit=25)
        control = await self._repo.get_control_state(name)
        config = control.get("config") if control else {}
        if isinstance(config, str):
            config = json.loads(config)
        timer = timer_by_key(name)
        return WorkerDetailResponse(
            **entry.model_dump(),
            runs=[entry for row in runs if (entry := self._run_entry(row)) is not None],
            config=config if isinstance(config, dict) else {},
            timer_mapping={
                "timer_key": timer.key if timer else None,
                "systemd_timer": timer.systemd_timer if timer else None,
                "schedule": entry.schedule,
            },
        )

    async def list_runs(self, name: str, *, limit: int = 50) -> WorkerRunListResponse | None:
        worker = worker_by_key(name)
        if worker is None:
            return None
        rows = await self._repo.fetch_runs(worker.audit_worker_names, limit=limit)
        return WorkerRunListResponse(
            name=name,
            runs=[entry for row in rows if (entry := self._run_entry(row))],
        )

    async def get_config(self, name: str) -> WorkerConfigResponse | None:
        worker = worker_by_key(name)
        if worker is None:
            return None
        control = await self._repo.get_control_state(name)
        config = control.get("config") if control else {}
        if isinstance(config, str):
            config = json.loads(config)
        return WorkerConfigResponse(
            name=name,
            config=config if isinstance(config, dict) else {},
            editable=worker.supports_config,
        )

    async def get_logs(self, name: str, *, limit: int = 100) -> WorkerLogsResponse | None:
        worker = worker_by_key(name)
        if worker is None:
            return None
        runs = await self._repo.fetch_runs(worker.audit_worker_names, limit=limit)
        lines: list[WorkerLogEntry] = []
        for row in runs:
            if row.get("error_message"):
                lines.append(
                    WorkerLogEntry(
                        ts=row.get("ended_at") or row["started_at"],
                        level="error",
                        source="audit_worker_runs",
                        message=str(row["error_message"]),
                        run_id=int(row["run_id"]),
                    ),
                )
            if row.get("error_stack"):
                lines.append(
                    WorkerLogEntry(
                        ts=row.get("ended_at") or row["started_at"],
                        level="trace",
                        source="audit_worker_runs",
                        message=str(row["error_stack"])[:4000],
                        run_id=int(row["run_id"]),
                    ),
                )
        journal_lines: list[str] = []
        if worker.systemd_service and self._systemd.available:
            journal_lines = await self._systemd.journal_tail(worker.systemd_service, lines=50)
        for raw in journal_lines:
            lines.append(
                WorkerLogEntry(
                    ts=WorkersRepository.utc_now(),
                    level="info",
                    source="journal",
                    message=raw[:4000],
                    run_id=None,
                ),
            )
        return WorkerLogsResponse(
            name=name,
            lines=lines[:limit],
            journal_available=self._systemd.available and bool(worker.systemd_service),
        )

    async def _audit_action(
        self,
        *,
        actor: str,
        action: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> None:
        await write_audit_log(
            self._conn,
            actor=actor,
            action=action,
            entity_type="worker",
            entity_id=entity_id,
            payload=payload,
        )

    def _action_response(
        self,
        name: str,
        action: str,
        *,
        systemd: SystemdResult | None,
        audited: bool,
        reason: str,
    ) -> WorkerActionResponse:
        if systemd is None:
            status = "recorded"
            message = "Action audited; no host execution on this environment."
        elif not systemd.attempted:
            status = "gap"
            message = systemd.message
        elif systemd.success:
            status = "ok"
            message = systemd.message
        else:
            status = "failed"
            message = systemd.message
        return WorkerActionResponse(
            name=name,
            action=action,
            status=status,
            message=message,
            audited=audited,
            systemd_unit=systemd.unit if systemd else None,
            reason=reason,
        )

    async def force_run(self, name: str, *, actor: str, reason: str) -> WorkerActionResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_run:
            return None
        systemd_result: SystemdResult | None = None
        if self._systemd.can_control(worker.systemd_service) and worker.systemd_service:
            systemd_result = await self._systemd.start_service(worker.systemd_service)
        await self._audit_action(
            actor=actor,
            action="workers.run",
            entity_id=name,
            payload={"reason": reason, "systemd": systemd_result.message if systemd_result else None},
        )
        return self._action_response(
            name,
            "run",
            systemd=systemd_result,
            audited=True,
            reason=reason,
        )

    async def stop_worker(self, name: str, *, actor: str, reason: str) -> WorkerActionResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_stop:
            return None
        systemd_result: SystemdResult | None = None
        if self._systemd.can_control(worker.systemd_service) and worker.systemd_service:
            systemd_result = await self._systemd.stop_service(worker.systemd_service)
        await self._audit_action(
            actor=actor,
            action="workers.stop",
            entity_id=name,
            payload={"reason": reason, "systemd": systemd_result.message if systemd_result else None},
        )
        return self._action_response(
            name,
            "stop",
            systemd=systemd_result,
            audited=True,
            reason=reason,
        )

    async def pause_worker(self, name: str, *, actor: str, reason: str) -> WorkerActionResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_pause:
            return None
        await self._repo.set_paused(name, True, updated_by=actor)
        await self._audit_action(
            actor=actor,
            action="workers.pause",
            entity_id=name,
            payload={"reason": reason, "advisory_only": True},
        )
        return WorkerActionResponse(
            name=name,
            action="pause",
            status="recorded",
            message="Pause flag stored (advisory — workers do not consume yet).",
            audited=True,
            systemd_unit=None,
            reason=reason,
        )

    async def resume_worker(self, name: str, *, actor: str, reason: str) -> WorkerActionResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_pause:
            return None
        await self._repo.set_paused(name, False, updated_by=actor)
        await self._audit_action(
            actor=actor,
            action="workers.resume",
            entity_id=name,
            payload={"reason": reason, "advisory_only": True},
        )
        return WorkerActionResponse(
            name=name,
            action="resume",
            status="recorded",
            message="Pause cleared (advisory — workers do not consume yet).",
            audited=True,
            systemd_unit=None,
            reason=reason,
        )

    async def retry_run(
        self,
        name: str,
        run_id: int,
        *,
        actor: str,
        reason: str,
    ) -> WorkerActionResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_retry:
            return None
        failed = await self._repo.fetch_run_by_id(run_id)
        if failed is None or str(failed.get("worker_name")) not in worker.audit_worker_names:
            return None
        systemd_result: SystemdResult | None = None
        if self._systemd.can_control(worker.systemd_service) and worker.systemd_service:
            systemd_result = await self._systemd.start_service(worker.systemd_service)
        await self._audit_action(
            actor=actor,
            action="workers.retry",
            entity_id=name,
            payload={
                "reason": reason,
                "run_id": run_id,
                "systemd": systemd_result.message if systemd_result else None,
            },
        )
        return self._action_response(
            name,
            "retry",
            systemd=systemd_result,
            audited=True,
            reason=reason,
        )

    async def patch_config(
        self,
        name: str,
        body: WorkerConfigPatchRequest,
        *,
        actor: str,
    ) -> WorkerConfigResponse | None:
        worker = worker_by_key(name)
        if worker is None or not worker.supports_config:
            return None
        await self._repo.patch_config(name, body.config, updated_by=actor)
        await self._audit_action(
            actor=actor,
            action="workers.config.patch",
            entity_id=name,
            payload={"reason": body.reason, "config_keys": sorted(body.config.keys())},
        )
        return await self.get_config(name)

    async def _build_timer_entry(
        self,
        timer: TimerDefinition,
        control_states: dict[str, dict[str, Any]],
        next_runs: dict[str, str | None],
    ) -> TimerRegistryEntry:
        control = control_states.get(timer.key, {})
        schedule = str(control.get("schedule_override") or timer.schedule)
        gaps = self._gap_dtos(timer.control_gaps)
        if not timer.supports_stop or not self._systemd.can_control(timer.systemd_timer):
            gaps.append(
                WorkerControlGap(
                    action="stop",
                    reason="Timer stop requires systemd on Linux with installed unit.",
                ),
            )
        return TimerRegistryEntry(
            name=timer.key,
            title=timer.title,
            worker_key=timer.worker_key,
            systemd_timer=timer.systemd_timer,
            systemd_service=timer.systemd_service,
            schedule=schedule,
            enabled=bool(control.get("enabled", True)),
            next_run=next_runs.get(timer.key),
            control_gaps=gaps,
            supports_trigger=timer.supports_trigger,
            supports_enable=timer.supports_enable,
            supports_disable=timer.supports_disable,
            supports_schedule_edit=timer.supports_schedule_edit,
        )

    async def list_timers(self) -> TimerListResponse:
        control_states = await self._repo.list_control_states()
        next_runs: dict[str, str | None] = {}
        for timer in CANONICAL_TIMERS:
            if self._systemd.available:
                next_runs[timer.key] = await self._systemd.timer_next_elapsed(timer.systemd_timer)
            else:
                next_runs[timer.key] = None
        timers = [
            await self._build_timer_entry(timer, control_states, next_runs)
            for timer in CANONICAL_TIMERS
        ]
        return TimerListResponse(
            mode=self.mode,
            timers=timers,
            checked_at=WorkersRepository.utc_now(),
        )

    async def get_timer(self, name: str) -> TimerDetailResponse | None:
        timer = timer_by_key(name)
        if timer is None:
            return None
        listing = await self.list_timers()
        entry = next((row for row in listing.timers if row.name == name), None)
        if entry is None:
            return None
        worker = await self.get_worker(timer.worker_key)
        return TimerDetailResponse(
            **entry.model_dump(),
            worker=worker,
        )

    async def _timer_action(
        self,
        name: str,
        action: str,
        *,
        actor: str,
        reason: str,
        systemd_coro: Any,
        audit_action: str,
        extra: dict[str, Any] | None = None,
    ) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None:
            return None
        systemd_result: SystemdResult = await systemd_coro(timer.systemd_timer)
        payload = {"reason": reason, "systemd": systemd_result.message, **(extra or {})}
        await write_audit_log(
            self._conn,
            actor=actor,
            action=audit_action,
            entity_type="timer",
            entity_id=name,
            payload=payload,
        )
        if not systemd_result.attempted:
            status = "gap"
        elif systemd_result.success:
            status = "ok"
        else:
            status = "failed"
        return TimerActionResponse(
            name=name,
            action=action,
            status=status,
            message=systemd_result.message,
            audited=True,
            reason=reason,
        )

    async def trigger_timer(self, name: str, *, actor: str, reason: str) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_trigger:
            return None
        return await self._timer_action(
            name,
            "trigger",
            actor=actor,
            reason=reason,
            systemd_coro=self._systemd.trigger_timer,
            audit_action="timers.trigger",
        )

    async def enable_timer(self, name: str, *, actor: str, reason: str) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_enable:
            return None
        await self._repo.set_timer_enabled(name, True, updated_by=actor)
        return await self._timer_action(
            name,
            "enable",
            actor=actor,
            reason=reason,
            systemd_coro=self._systemd.enable_timer,
            audit_action="timers.enable",
            extra={"enabled": True},
        )

    async def disable_timer(self, name: str, *, actor: str, reason: str) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_disable:
            return None
        await self._repo.set_timer_enabled(name, False, updated_by=actor)
        return await self._timer_action(
            name,
            "disable",
            actor=actor,
            reason=reason,
            systemd_coro=self._systemd.disable_timer,
            audit_action="timers.disable",
            extra={"enabled": False},
        )

    async def start_timer(self, name: str, *, actor: str, reason: str) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_start:
            return None
        return await self._timer_action(
            name,
            "start",
            actor=actor,
            reason=reason,
            systemd_coro=self._systemd.start_timer,
            audit_action="timers.start",
        )

    async def stop_timer(self, name: str, *, actor: str, reason: str) -> TimerActionResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_stop:
            return None
        return await self._timer_action(
            name,
            "stop",
            actor=actor,
            reason=reason,
            systemd_coro=self._systemd.stop_timer,
            audit_action="timers.stop",
        )

    async def patch_timer_schedule(
        self,
        name: str,
        body: TimerSchedulePatchRequest,
        *,
        actor: str,
    ) -> TimerDetailResponse | None:
        timer = timer_by_key(name)
        if timer is None or not timer.supports_schedule_edit:
            return None
        await self._repo.patch_schedule(name, body.schedule, updated_by=actor)
        await write_audit_log(
            self._conn,
            actor=actor,
            action="timers.schedule.patch",
            entity_type="timer",
            entity_id=name,
            payload={"reason": body.reason, "schedule": body.schedule, "advisory_only": True},
        )
        return await self.get_timer(name)

    async def timer_journal(self, name: str, *, limit: int = 100) -> TimerJournalResponse | None:
        timer = timer_by_key(name)
        if timer is None:
            return None
        lines: list[TimerJournalEntry] = []
        if self._systemd.available:
            raw = await self._systemd.journal_tail(timer.systemd_timer, lines=limit)
            for text in raw:
                lines.append(
                    TimerJournalEntry(
                        ts=WorkersRepository.utc_now(),
                        message=text[:4000],
                        source="journal",
                    ),
                )
        worker = worker_by_key(timer.worker_key)
        if worker:
            runs = await self._repo.fetch_runs(worker.audit_worker_names, limit=20)
            for row in runs:
                lines.append(
                    TimerJournalEntry(
                        ts=row["started_at"],
                        message=f"{row['worker_name']} {row['status']} run_id={row['run_id']}",
                        source="audit_worker_runs",
                    ),
                )
        return TimerJournalResponse(
            name=name,
            entries=lines[:limit],
            journal_available=self._systemd.available,
        )
