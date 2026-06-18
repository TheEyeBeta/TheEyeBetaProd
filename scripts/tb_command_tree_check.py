#!/usr/bin/env python3
"""Verify tb CLI command groups resolve (CI regression gate)."""

from __future__ import annotations

import subprocess
import sys

REQUIRED_GROUPS = (
    "status",
    "prelive",
    "now",
    "engine",
    "canonical",
    "intraday",
    "trask",
    "workers",
    "pipeline",
    "universe",
    "instrument",
    "snapshots",
    "prices",
    "indicators",
    "returns",
    "snapshot",
    "export",
    "fundamentals",
    "plot",
    "quant",
    "backtest",
    "strategies",
    "signals",
    "sql",
    "db",
    "secrets",
    "deploy",
    "config",
    "meta",
    "logs",
    "restart",
)


def main() -> int:
    """Run ``tb --help`` and assert required command groups appear."""
    proc = subprocess.run(  # noqa: S603
        ["uv", "run", "--project", "tb", "tb", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    missing = [name for name in REQUIRED_GROUPS if name not in proc.stdout]
    if missing:
        print(f"Missing tb command groups: {missing}", file=sys.stderr)
        return 1
    print(f"tb_command_tree_check: OK ({len(REQUIRED_GROUPS)} groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
