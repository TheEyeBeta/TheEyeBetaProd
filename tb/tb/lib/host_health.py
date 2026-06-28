"""Host memory and legacy-daemon checks for operator tooling."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Units archived in deploy/systemd/archived/ — must stay masked/inactive on Prod.
LEGACY_DAEMON_UNITS: tuple[str, ...] = (
    "theeyebeta-engine.service",
    "theeyebeta-trask.service",
    "theeyebeta-watcher.service",
)

# Primary offender: old Local-tree trade engine (~1.7 GiB when running).
LEGACY_ENGINE_UNIT = "theeyebeta-engine.service"

SWAP_WARN_PCT = 50.0
SWAP_FAIL_PCT = 85.0
MIN_AVAILABLE_KB = 2 * 1024 * 1024  # 2 GiB


@dataclass(frozen=True, slots=True)
class MemoryStats:
    """Parsed /proc/meminfo snapshot."""

    mem_total_kb: int
    mem_available_kb: int
    swap_total_kb: int
    swap_free_kb: int

    @property
    def swap_used_pct(self) -> float:
        if self.swap_total_kb <= 0:
            return 0.0
        used = self.swap_total_kb - self.swap_free_kb
        return max(0.0, used / self.swap_total_kb * 100.0)

    @property
    def mem_available_gib(self) -> float:
        return self.mem_available_kb / (1024**2)

    @property
    def swap_used_gib(self) -> float:
        used = max(0, self.swap_total_kb - self.swap_free_kb)
        return used / (1024**2)


@dataclass(frozen=True, slots=True)
class LegacyDaemonStatus:
    """Active state for one legacy systemd unit."""

    unit: str
    active: str  # systemctl ActiveState (active, inactive, failed, …)


def read_memory_stats(meminfo_path: Path = Path("/proc/meminfo")) -> MemoryStats:
    """Read MemTotal, MemAvailable, SwapTotal, and SwapFree from procfs."""
    fields: dict[str, int] = {}
    text = meminfo_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            fields[key] = int(value.strip().split()[0])
    missing = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"} - fields.keys()
    if missing:
        msg = f"/proc/meminfo missing keys: {', '.join(sorted(missing))}"
        raise ValueError(msg)
    return MemoryStats(
        mem_total_kb=fields["MemTotal"],
        mem_available_kb=fields["MemAvailable"],
        swap_total_kb=fields["SwapTotal"],
        swap_free_kb=fields["SwapFree"],
    )


def memory_check_status(stats: MemoryStats) -> tuple[str, str]:
    """Return (PASS|WARN|FAIL, detail) for host memory pressure."""
    parts = [
        f"available={stats.mem_available_gib:.1f}GiB",
        f"swap_used={stats.swap_used_pct:.0f}% ({stats.swap_used_gib:.1f}GiB)",
    ]
    detail = "; ".join(parts)

    if stats.swap_used_pct >= SWAP_FAIL_PCT:
        return "FAIL", f"{detail} (swap >={SWAP_FAIL_PCT:.0f}% is a launch blocker)"
    if stats.swap_used_pct >= SWAP_WARN_PCT:
        return (
            "WARN",
            f"{detail} (swap >={SWAP_WARN_PCT:.0f}% — expect sluggish workers)",
        )
    if stats.mem_available_kb < MIN_AVAILABLE_KB:
        return "WARN", f"{detail} (available <2GiB — pipeline jobs may OOM)"
    return "PASS", detail


def _systemctl_active(unit: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["/usr/bin/systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return f"unknown ({exc})"
    state = proc.stdout.strip() or proc.stderr.strip() or "unknown"
    return state


def probe_legacy_daemons(
    units: tuple[str, ...] = LEGACY_DAEMON_UNITS,
) -> list[LegacyDaemonStatus]:
    """Return ActiveState for each legacy unit."""
    return [
        LegacyDaemonStatus(unit=unit, active=_systemctl_active(unit)) for unit in units
    ]


def legacy_daemon_check_status(
    statuses: list[LegacyDaemonStatus] | None = None,
) -> tuple[str, str]:
    """Return (PASS|WARN|FAIL, detail) for masked-unit drift."""
    rows = statuses if statuses is not None else probe_legacy_daemons()
    active = [row for row in rows if row.active == "active"]
    if not active:
        return "PASS", "no legacy Local-tree daemons active"

    names = ", ".join(row.unit for row in active)
    if any(row.unit == LEGACY_ENGINE_UNIT for row in active):
        return (
            "FAIL",
            f"{names} running — stop/mask per docs/ops/remediation-2026-06-15.md "
            f"(engine alone uses ~1.7GiB)",
        )
    return "WARN", f"{names} running — should be masked on Prod host"
