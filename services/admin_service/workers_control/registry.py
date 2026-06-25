"""Canonical worker and timer registry aligned with control matrix and audit tables."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ControlGap:
    """A control action not safely wired end-to-end."""

    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class WorkerDefinition:
    """One schedulable worker in the Terminal registry."""

    key: str
    title: str
    audit_worker_names: tuple[str, ...]
    systemd_service: str | None
    systemd_timer: str | None
    schedule: str
    source_path: str
    priority: str = "Medium"
    supports_run: bool = True
    supports_stop: bool = False
    supports_pause: bool = False
    supports_retry: bool = True
    supports_config: bool = True
    control_gaps: tuple[ControlGap, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class TimerDefinition:
    """Systemd timer mapped to a worker."""

    key: str
    title: str
    worker_key: str
    systemd_timer: str
    systemd_service: str | None
    schedule: str
    supports_trigger: bool = True
    supports_enable: bool = True
    supports_disable: bool = True
    supports_start: bool = True
    supports_stop: bool = False
    supports_schedule_edit: bool = True
    control_gaps: tuple[ControlGap, ...] = field(default_factory=tuple)


_PAUSE_GAP = ControlGap(
    action="pause",
    reason="Pause flag is stored in admin_worker_control; worker processes do not consume it yet.",
)
_RESUME_GAP = ControlGap(
    action="resume",
    reason="Resume clears advisory pause only; worker processes do not consume it yet.",
)
_SYSTEMD_GAP = ControlGap(
    action="systemd",
    reason="systemd control requires Linux host with installed units.",
)
_BACKUP_GAPS = (
    ControlGap(action="stop", reason="Backup job is a shell script without a long-running service."),
    ControlGap(action="pause", reason="Backup script has no pause hook."),
    _SYSTEMD_GAP,
)


CANONICAL_WORKERS: tuple[WorkerDefinition, ...] = (
    WorkerDefinition(
        key="gap-sentinel",
        title="Gap Sentinel",
        audit_worker_names=("GapSentinelWorker",),
        systemd_service="theeye-gap-sentinel.service",
        systemd_timer="theeye-gap-sentinel.timer",
        schedule="Mon-Fri 07:30 UTC",
        source_path="workers/gap_sentinel_worker.py",
        priority="High",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="macro",
        title="Macro pipeline",
        audit_worker_names=("MacroIngestionWorker", "MacroRegimeWorker"),
        systemd_service="theeye-macro.service",
        systemd_timer="theeye-macro.timer",
        schedule="Mon-Fri 21:20 UTC",
        source_path="workers/macro_pipeline.py",
        priority="Medium",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="massive-ingest",
        title="Massive daily ingest",
        audit_worker_names=("MassiveDailyIngestionWorker",),
        systemd_service="theeye-massive-ingest.service",
        systemd_timer="theeye-massive-ingest.timer",
        schedule="Mon-Fri 21:30 UTC",
        source_path="workers/massive_ingestion_worker.py",
        priority="High",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="daily-pipeline",
        title="Daily pipeline",
        audit_worker_names=("daily_pipeline",),
        systemd_service="theeye-daily-pipeline.service",
        systemd_timer="theeye-daily-pipeline.timer",
        schedule="Mon-Fri 21:35 UTC",
        source_path="workers/daily_pipeline_runner.py",
        priority="Medium",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="sector",
        title="Sector aggregation",
        audit_worker_names=("SectorAggregationWorker",),
        systemd_service="theeye-sector.service",
        systemd_timer="theeye-sector.timer",
        schedule="Mon-Fri 22:05 UTC",
        source_path="workers/sector_aggregation_worker.py",
        priority="Medium",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="supabase-sync",
        title="Supabase sync",
        audit_worker_names=("SupabaseSyncV2",),
        systemd_service="theeye-supabase-sync.service",
        systemd_timer="theeye-supabase-sync.timer",
        schedule="Mon-Fri 22:20 UTC",
        source_path="workers/supabase_sync_worker.py",
        priority="Medium",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="intraday-ingest",
        title="Intraday ingest",
        audit_worker_names=("IntradayIngestionWorker",),
        systemd_service="theeye-intraday-ingest.service",
        systemd_timer="theeye-intraday-ingest.timer",
        schedule="Mon-Fri */15 min",
        source_path="workers/intraday_ingestion_worker.py",
        priority="High",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
    WorkerDefinition(
        key="backup",
        title="Database backup",
        audit_worker_names=(),
        systemd_service="theeye-backup.service",
        systemd_timer="theeye-backup.timer",
        schedule="Daily 02:00 UTC",
        source_path="scripts/backup_db.sh",
        priority="Medium",
        supports_stop=False,
        supports_pause=False,
        supports_retry=False,
        control_gaps=_BACKUP_GAPS,
    ),
    WorkerDefinition(
        key="local-daily",
        title="Local daily (TheEyeBeta)",
        audit_worker_names=(),
        systemd_service="theeyebeta-daily.service",
        systemd_timer="theeyebeta-daily.timer",
        schedule="Mon-Fri 18:00",
        source_path="TheEyeBetaLocal/scripts/systemd/theeyebeta-daily.timer",
        priority="Medium",
        supports_stop=True,
        supports_pause=True,
        control_gaps=(_PAUSE_GAP, _RESUME_GAP, _SYSTEMD_GAP),
    ),
)

CANONICAL_TIMERS: tuple[TimerDefinition, ...] = tuple(
    TimerDefinition(
        key=worker.key,
        title=f"Timer: {worker.systemd_timer or worker.key}",
        worker_key=worker.key,
        systemd_timer=worker.systemd_timer or f"{worker.key}.timer",
        systemd_service=worker.systemd_service,
        schedule=worker.schedule,
        supports_stop=worker.supports_stop,
        control_gaps=worker.control_gaps,
    )
    for worker in CANONICAL_WORKERS
    if worker.systemd_timer
)

_WORKERS_BY_KEY = {worker.key: worker for worker in CANONICAL_WORKERS}
_TIMERS_BY_KEY = {timer.key: timer for timer in CANONICAL_TIMERS}


def worker_by_key(key: str) -> WorkerDefinition | None:
    return _WORKERS_BY_KEY.get(key)


def timer_by_key(key: str) -> TimerDefinition | None:
    return _TIMERS_BY_KEY.get(key)


def all_worker_keys() -> tuple[str, ...]:
    return tuple(_WORKERS_BY_KEY.keys())


def all_timer_keys() -> tuple[str, ...]:
    return tuple(_TIMERS_BY_KEY.keys())
