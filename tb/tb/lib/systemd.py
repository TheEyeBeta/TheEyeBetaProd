"""systemd helpers for worker timers and journals."""

from __future__ import annotations

import subprocess


def list_timers(pattern: str = "theeye-*") -> str:
    """Return systemctl list-timers output."""
    try:
        proc = subprocess.run(  # noqa: S603
            ["/usr/bin/systemctl", "list-timers", pattern, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.stdout.strip() or proc.stderr.strip() or "(no timers)"
    except OSError as exc:
        return f"(systemctl unavailable: {exc})"


def journal_tail(unit: str, *, lines: int = 100, follow: bool = False) -> int:
    """Tail journal for a systemd unit."""
    cmd = ["journalctl", "-u", unit, f"-n{lines}", "--no-pager"]
    if follow:
        cmd.append("-f")
    proc = subprocess.run(cmd, check=False)  # noqa: S603
    return proc.returncode
