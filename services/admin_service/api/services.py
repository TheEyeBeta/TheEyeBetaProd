"""Admin services API — systemd unit status + whitelisted restart."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn
from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    RestartServiceRequest,
    RestartServiceResponse,
    ServiceStatusEntry,
    ServiceStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/services", tags=["services"])

# Maps logical service name (API key) → systemd unit name.
# Expand as more services gain systemd units.
RESTARTABLE_SERVICES: dict[str, str] = {
    "admin-service": "theeyebeta-admin",
    "llm-gateway": "theeyebeta-litellm",
}

# Full set reported by /status — superset of RESTARTABLE_SERVICES.
ALL_UNITS: dict[str, str] = {
    **RESTARTABLE_SERVICES,
    "nats": "nats",
    "redis": "redis-server",
}


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


async def _systemctl_show(unit: str) -> dict[str, str]:
    """Query ``systemctl show`` for a unit's active state and timestamps."""
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "show",
        unit,
        "--property=ActiveState,SubState,ActiveEnterTimestamp",
        "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    props: dict[str, str] = {}
    for line in stdout.decode().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


def _parse_systemd_ts(raw: str) -> datetime | None:
    """Parse systemd's ``ActiveEnterTimestamp`` into a UTC datetime.

    systemd emits: ``Thu 2026-06-12 14:23:45 UTC``
    Strip the day-of-week prefix and parse the remainder.
    """
    if not raw or raw.startswith("0") or raw == "n/a":
        return None
    parts = raw.split()
    # Last three tokens are always: YYYY-MM-DD HH:MM:SS TZ
    clean = " ".join(parts[-3:]) if len(parts) >= 3 else raw
    try:
        dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S %Z")
        return dt.replace(tzinfo=UTC)
    except ValueError:
        return None


async def _unit_to_entry(name: str, unit: str) -> ServiceStatusEntry:
    """Map a systemd unit to :class:`ServiceStatusEntry`."""
    props = await _systemctl_show(unit)
    active_state = props.get("ActiveState", "unknown")
    sub_state = props.get("SubState", "unknown")

    started_at: datetime | None = _parse_systemd_ts(props.get("ActiveEnterTimestamp", ""))
    uptime_seconds: int | None = None
    if started_at is not None:
        uptime_seconds = max(0, int((datetime.now(tz=UTC) - started_at).total_seconds()))

    return ServiceStatusEntry(
        name=name,
        image=unit,  # repurposes Docker field — holds unit name
        state=f"{active_state} ({sub_state})",
        health="healthy" if active_state == "active" else "unhealthy",
        started_at=started_at,
        uptime_seconds=uptime_seconds,
        container_id=unit,  # repurposes Docker field — holds unit name
    )


def register_services_routes(limiter: Limiter) -> APIRouter:
    """Attach systemd status + restart handlers."""

    @router.get("/status", response_model=ServiceStatusResponse)
    async def list_service_status(
        user: CurrentUser,
    ) -> ServiceStatusResponse:
        """Return systemd unit status for all known TheEyeBeta services."""
        entries = list(
            await asyncio.gather(
                *[_unit_to_entry(name, unit) for name, unit in ALL_UNITS.items()]
            )
        )
        log.info("admin_services_status_listed", count=len(entries), sub=user["sub"])
        return ServiceStatusResponse(services=entries, network="systemd")

    @router.post("/{name}/restart", response_model=RestartServiceResponse)
    @limiter.limit("20/minute")
    async def restart_service(
        request: Request,  # noqa: ARG001 — required by slowapi
        name: str,
        body: RestartServiceRequest,
        user: CurrentUser,
        conn: DbConn,
    ) -> RestartServiceResponse:
        """Restart a whitelisted systemd unit and audit-log the action."""
        if name not in RESTARTABLE_SERVICES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Service '{name}' is not in the restart whitelist",
            )

        unit = RESTARTABLE_SERVICES[name]
        actor = _actor(user)

        proc = await asyncio.create_subprocess_exec(
            "sudo",
            "systemctl",
            "restart",
            unit,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode().strip()
            log.error("admin_service_restart_failed", service=name, unit=unit, error=err)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"systemctl refused to restart '{unit}': {err}",
            )

        await asyncio.sleep(1)
        props = await _systemctl_show(unit)
        new_state = props.get("ActiveState", "unknown")

        await write_audit_log(
            conn,
            actor=actor,
            action="restart.service",
            entity_type="service",
            entity_id=name,
            payload={**body.model_dump(mode="json"), "unit": unit},
        )

        log.info("admin_service_restarted", service=name, unit=unit, sub=user["sub"])
        return RestartServiceResponse(
            name=name,
            container_id=unit,  # repurposes Docker field — holds unit name
            restarted=True,
            state=new_state,
        )

    return router
