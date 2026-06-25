"""Optional systemd probes — never expose secrets."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class SystemdResult:
    """Outcome of a systemd invocation."""

    attempted: bool
    success: bool
    message: str
    unit: str | None = None


class SystemdProbe:
    """Best-effort systemd control on Linux hosts."""

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._enabled = sys.platform.startswith("linux") if enabled is None else enabled

    @property
    def available(self) -> bool:
        return self._enabled

    async def _run(self, *args: str) -> SystemdResult:
        unit = args[-1] if args else None
        if not self._enabled:
            return SystemdResult(
                attempted=False,
                success=False,
                message="systemd control unavailable on this host",
                unit=unit,
            )
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        ok = proc.returncode == 0
        detail = (stdout or stderr or b"").decode(errors="replace").strip()
        if not ok:
            log.warning("systemd_command_failed", cmd=list(args), detail=detail[:500])
        return SystemdResult(
            attempted=True,
            success=ok,
            message=detail or ("ok" if ok else f"exit {proc.returncode}"),
            unit=unit,
        )

    def can_control(self, unit: str | None) -> bool:
        return bool(unit) and self._enabled

    async def start_service(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "start", unit)

    async def stop_service(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "stop", unit)

    async def trigger_timer(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "start", unit)

    async def enable_timer(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "enable", unit)

    async def disable_timer(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "disable", unit)

    async def start_timer(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "start", unit)

    async def stop_timer(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "stop", unit)

    async def unit_status(self, unit: str) -> SystemdResult:
        return await self._run("systemctl", "is-active", unit)

    async def timer_next_elapsed(self, unit: str) -> str | None:
        if not self._enabled:
            return None
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "list-timers",
            unit,
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        lines = stdout.decode(errors="replace").strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) >= 2:
            return parts[0]
        return None

    async def journal_tail(self, unit: str, *, lines: int = 50) -> list[str]:
        if not self._enabled:
            return []
        proc = await asyncio.create_subprocess_exec(
            "journalctl",
            "-u",
            unit,
            "-n",
            str(lines),
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return []
        return stdout.decode(errors="replace").splitlines()
