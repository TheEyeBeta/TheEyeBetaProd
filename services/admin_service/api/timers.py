"""Systemd timer visibility and manual trigger APIs."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import structlog
from audit_log import write_audit_log
from deps import DbConn, RedisOpsDep
from fastapi import APIRouter, HTTPException, Request, status
from rbac import Role, require_role
from redis.asyncio import Redis
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    TimerEntry,
    TimersListResponse,
    TimerTriggerRequest,
    TimerTriggerResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/timers", tags=["timers"])

# Whitelisted systemd timer short names (12 production timers).
TIMER_ALLOWLIST: set[str] = {
    "backup",
    "gap-sentinel",
    "news-ingest",
    "risk-metrics-refresh",
    "market-cap",
    "macro",
    "massive-ingest",
    "macro-refresh",
    "daily-pipeline",
    "sector",
    "supabase-sync",
    "intraday-ingest",
}

WHITELISTED_TIMERS: dict[str, str] = {
    "macro": "theeye-macro.timer",
    "massive-ingest": "theeye-massive-ingest.timer",
    "intraday-ingest": "theeye-intraday-ingest.timer",
    "daily-pipeline": "theeye-daily-pipeline.timer",
    "gap-sentinel": "theeye-gap-sentinel.timer",
    "sector": "theeye-sector.timer",
    "market-cap": "theeye-market-cap.timer",
    "supabase-sync": "theeye-supabase-sync.timer",
    "macro-refresh": "theeye-macro-refresh.timer",
    "risk-metrics-refresh": "theeye-risk-metrics-refresh.timer",
    "backup": "theeye-backup.timer",
    "news-ingest": "theeye-news-ingest.timer",
}

_TS_RE = re.compile(
    r"^(?P<day>\w+)\s+(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+(?P<tz>\w+)$",
)


def _parse_systemd_ts(raw: str) -> datetime | None:
    """Parse systemd timestamp into UTC datetime."""
    raw = raw.strip()
    if not raw or raw in {"n/a", "-"}:
        return None
    match = _TS_RE.match(raw)
    if not match:
        return None
    try:
        dt = datetime.strptime(
            f"{match.group('date')} {match.group('time')} {match.group('tz')}",
            "%Y-%m-%d %H:%M:%S %Z",
        )
        return dt.replace(tzinfo=UTC)
    except ValueError:
        return None


async def _systemctl_show_timer(unit: str) -> dict[str, str]:
    """Query timer unit properties."""
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "show",
        unit,
        "--property=ActiveState,UnitFileState,LastTriggerUSec,NextElapseUSecRealtime",
        "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    props: dict[str, str] = {}
    for line in stdout.decode().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


async def fetch_timer_entry(name: str, unit: str) -> TimerEntry:
    """Build one timer entry from systemctl."""
    props = await _systemctl_show_timer(unit)
    active = props.get("ActiveState", "unknown")
    file_state = props.get("UnitFileState", "unknown")
    if active == "active":
        timer_status = "active"
    elif file_state == "disabled":
        timer_status = "inactive"
    elif active == "failed":
        timer_status = "failed"
    else:
        timer_status = "inactive"

    last_raw = props.get("LastTriggerUSec", "")
    next_raw = props.get("NextElapseUSecRealtime", "")

    return TimerEntry(
        name=name,
        unit=unit,
        schedule=unit.replace(".timer", ""),
        last_trigger=_parse_systemd_ts(last_raw) if last_raw else None,
        next_trigger=_parse_systemd_ts(next_raw) if next_raw else None,
        status=timer_status,
    )


async def fetch_timers_summary() -> dict[str, int]:
    """Return active/inactive counts for ops pulse."""
    entries = await asyncio.gather(
        *[fetch_timer_entry(name, unit) for name, unit in WHITELISTED_TIMERS.items()],
    )
    active = sum(1 for e in entries if e.status == "active")
    inactive = sum(1 for e in entries if e.status != "active")
    return {"active": active, "inactive": inactive}


_TIMER_LOCK_PREFIX = "timer:run_lock:"


def _actor(user: dict[str, str]) -> str:
    return f"admin-api:{user['sub']}"


async def _acquire_timer_lock(redis: Redis, name: str) -> None:
    """Prevent concurrent manual timer triggers."""
    lock_key = f"{_TIMER_LOCK_PREFIX}{name}"
    acquired = await redis.set(lock_key, "1", ex=3600, nx=True)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "timer_already_running", "message": f"Timer {name} is busy"},
        )


def register_timers_routes(limiter: Limiter) -> APIRouter:
    """Attach timer visibility and trigger handlers."""

    @router.get(
        "",
        response_model=TimersListResponse,
        summary="Systemd timers (READ_ONLY)",
    )
    async def list_timers(
        user: dict[str, str] = require_role(Role.READ_ONLY),
    ) -> TimersListResponse:
        """Return whitelisted systemd timer status."""
        entries = list(
            await asyncio.gather(
                *[fetch_timer_entry(name, unit) for name, unit in WHITELISTED_TIMERS.items()],
            ),
        )
        log.info("admin_timers_listed", count=len(entries), sub=user["sub"])
        return TimersListResponse(timers=entries, total=len(entries))

    @router.post(
        "/{name}/trigger",
        response_model=TimerTriggerResponse,
        summary="Trigger systemd timer (OPERATOR)",
    )
    @limiter.limit("10/minute")
    async def trigger_timer(
        request: Request,  # noqa: ARG001
        name: str,
        body: TimerTriggerRequest,
        conn: DbConn,
        redis: RedisOpsDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> TimerTriggerResponse:
        """Manually fire a whitelisted systemd timer."""
        if name not in TIMER_ALLOWLIST:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Timer {name!r} is not whitelisted",
            )
        unit = WHITELISTED_TIMERS[name]
        lock_key = f"{_TIMER_LOCK_PREFIX}{name}"
        await _acquire_timer_lock(redis, name)

        triggered_at = datetime.now(tz=UTC)
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "start",
                unit,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            exit_code = proc.returncode or 0
            if exit_code != 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"systemctl start failed: {stderr.decode().strip()}",
                )
        finally:
            await redis.delete(lock_key)

        actor = _actor(user)
        await write_audit_log(
            conn,
            actor=actor,
            action="trigger.timer",
            entity_type="systemd_timer",
            entity_id=name,
            payload={
                "unit": unit,
                "reason": body.reason,
                "triggered_at": triggered_at.isoformat(),
                "actor": user["sub"],
            },
        )

        log.info("admin_timer_triggered", timer=name, unit=unit, sub=user["sub"])
        return TimerTriggerResponse(
            name=name,
            unit=unit,
            triggered_at=triggered_at,
            triggered_by=user["sub"],
            exit_code=exit_code,
        )

    return router
