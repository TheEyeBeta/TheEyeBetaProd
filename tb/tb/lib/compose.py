"""Docker Compose wrappers for tb infra commands."""

from __future__ import annotations

import subprocess

from tb.lib.paths import COMPOSE_FILE, REPO_ROOT


def _compose_cmd(*args: str, follow: bool = False) -> list[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    return cmd


def compose_ps() -> subprocess.CompletedProcess[str]:
    """Return docker compose ps output."""
    return subprocess.run(  # noqa: S603
        _compose_cmd("ps", "--format", "json"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def compose_logs(service: str, *, tail: int = 100, follow: bool = False) -> int:
    """Tail service logs; returns process exit code."""
    args = ["logs", f"--tail={tail}", service]
    if follow:
        args.append("-f")
    proc = subprocess.run(_compose_cmd(*args), cwd=REPO_ROOT, check=False)  # noqa: S603
    return proc.returncode


def compose_restart(service: str) -> int:
    """Restart one compose service."""
    proc = subprocess.run(_compose_cmd("restart", service), cwd=REPO_ROOT, check=False)  # noqa: S603
    return proc.returncode


def compose_deploy(service: str | None = None) -> int:
    """Pull images and bring service(s) up."""
    pull = subprocess.run(
        _compose_cmd("pull", *([service] if service else [])),
        cwd=REPO_ROOT,
        check=False,
    )  # noqa: S603
    if pull.returncode != 0:
        return pull.returncode
    up_args = ["up", "-d", "--wait"]
    if service:
        up_args.append(service)
    proc = subprocess.run(_compose_cmd(*up_args), cwd=REPO_ROOT, check=False)  # noqa: S603
    return proc.returncode
