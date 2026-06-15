"""``tb prelive`` — go/no-go harness."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

app = typer.Typer(help="Pre-live go/no-go checks")

ROOT = Path(__file__).resolve().parents[3]


@app.callback(invoke_without_command=True)
def prelive(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Run read-only prelive checks (exit 1 on any FAIL)."""
    if ctx.invoked_subcommand is not None:
        return
    cmd = ["uv", "run", "python", "scripts/prelive_check.py"]
    if json_output:
        cmd.append("--json")
    proc = subprocess.run(cmd, cwd=ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)
