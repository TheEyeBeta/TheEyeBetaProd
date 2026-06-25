"""Allowlisted systemd probes — no arbitrary shell execution."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from services_control.logs import MAX_LOG_LINES, sanitize_log_lines

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class SystemdUnitStatus:
    """Parsed ``systemctl show`` properties for one unit."""

    active_state: str
    sub_state: str
    unit_file_state: str | None
    started_at: datetime | None
    uptime_seconds: int | None
    n_restarts: int | None
    memory_bytes: int | None
    cpu_nsec: int | None
    enabled: bool | None


@dataclass(frozen=True, slots=True)
class SystemdResult:
    """Outcome of an allowlisted systemd command."""

    attempted: bool
    success: bool
    message: str
    unit: str | None = None


class AllowlistedSystemdProbe:
    """Run fixed systemctl subcommands for allowlisted units only."""

    ALLOWED_COMMANDS = frozenset(
        {"show", "restart", "start", "stop", "enable", "disable", "is-active"},
    )

    def __init__(
        self,
        allowed_units: frozenset[str],
        *,
        enabled: bool | None = None,
    ) -> None:
        self._allowed = allowed_units
        self._enabled = sys.platform.startswith("linux") if enabled is None else enabled

    @property
    def available(self) -> bool:
        return self._enabled

    def _assert_allowed(self, unit: str) -> None:
        if unit not in self._allowed:
            msg = f"systemd unit not allowlisted: {unit!r}"
            raise ValueError(msg)

    async def _run(self, command: str, unit: str, *extra: str) -> SystemdResult:
        self._assert_allowed(unit)
        if command not in self.ALLOWED_COMMANDS:
            msg = f"systemctl subcommand not allowed: {command!r}"
            raise ValueError(msg)
        if not self._enabled:
            return SystemdResult(
                attempted=False,
                success=False,
                message="systemd control unavailable on this host",
                unit=unit,
            )
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            command,
            unit,
            *extra,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        ok = proc.returncode == 0
        detail = (stdout or stderr or b"").decode(errors="replace").strip()
        if not ok:
            log.warning("systemctl_failed", command=command, unit=unit, detail=detail[:500])
        return SystemdResult(
            attempted=True,
            success=ok,
            message=detail or ("ok" if ok else f"exit {proc.returncode}"),
            unit=unit,
        )

    @staticmethod
    def _parse_timestamp(raw: str) -> datetime | None:
        if not raw or raw.startswith("0") or raw == "n/a":
            return None
        parts = raw.split()
        clean = " ".join(parts[-3:]) if len(parts) >= 3 else raw
        try:
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S %Z")
            return dt.replace(tzinfo=UTC)
        except ValueError:
            return None

    async def show(self, unit: str) -> SystemdUnitStatus:
        result = await self._run(
            "show",
            unit,
            "--property=ActiveState,SubState,UnitFileState,ActiveEnterTimestamp,"
            "NRestarts,MemoryCurrent,CPUUsageNSec",
            "--no-pager",
        )
        props: dict[str, str] = {}
        if result.attempted and result.message:
            for line in result.message.splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    props[key.strip()] = value.strip()
        started_at = self._parse_timestamp(props.get("ActiveEnterTimestamp", ""))
        uptime_seconds: int | None = None
        if started_at is not None:
            uptime_seconds = max(0, int((datetime.now(tz=UTC) - started_at).total_seconds()))
        n_restarts: int | None = None
        if props.get("NRestarts", "").isdigit():
            n_restarts = int(props["NRestarts"])
        memory_bytes: int | None = None
        raw_mem = props.get("MemoryCurrent", "")
        if raw_mem.isdigit():
            memory_bytes = int(raw_mem)
        cpu_nsec: int | None = None
        raw_cpu = props.get("CPUUsageNSec", "")
        if raw_cpu.isdigit():
            cpu_nsec = int(raw_cpu)
        unit_file_state = props.get("UnitFileState") or None
        enabled: bool | None = None
        if unit_file_state:
            enabled = unit_file_state in {"enabled", "enabled-runtime", "linked", "linked-runtime"}
        return SystemdUnitStatus(
            active_state=props.get("ActiveState", "unknown"),
            sub_state=props.get("SubState", "unknown"),
            unit_file_state=unit_file_state,
            started_at=started_at,
            uptime_seconds=uptime_seconds,
            n_restarts=n_restarts,
            memory_bytes=memory_bytes,
            cpu_nsec=cpu_nsec,
            enabled=enabled,
        )

    async def restart(self, unit: str) -> SystemdResult:
        return await self._run("restart", unit)

    async def start(self, unit: str) -> SystemdResult:
        return await self._run("start", unit)

    async def stop(self, unit: str) -> SystemdResult:
        return await self._run("stop", unit)

    async def enable(self, unit: str) -> SystemdResult:
        return await self._run("enable", unit)

    async def disable(self, unit: str) -> SystemdResult:
        return await self._run("disable", unit)

    async def journal(self, unit: str, *, lines: int = MAX_LOG_LINES) -> list[str]:
        self._assert_allowed(unit)
        if not self._enabled:
            return []
        capped = min(lines, MAX_LOG_LINES)
        proc = await asyncio.create_subprocess_exec(
            "journalctl",
            "-u",
            unit,
            "-n",
            str(capped),
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        raw_lines = stdout.decode(errors="replace").splitlines()
        return sanitize_log_lines(raw_lines, limit=capped)
