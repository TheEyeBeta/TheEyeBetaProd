"""``tb backtest`` — backtest engine HTTP client."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import typer

app = typer.Typer(no_args_is_help=True, help="Backtest engine jobs")

DEFAULT_URL = os.environ.get("BACKTEST_ENGINE_URL", "http://127.0.0.1:7100")


@app.command("run")
def backtest_run(config: Path = typer.Argument(..., help="JSON config path")) -> None:
    """Submit a backtest job."""
    payload = json.loads(config.read_text(encoding="utf-8"))
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(f"{DEFAULT_URL}/backtest/run", json=payload)
    typer.echo(resp.text)
    raise typer.Exit(code=0 if resp.is_success else 1)


@app.command("status")
def backtest_status(run_id: str = typer.Argument(...)) -> None:
    """Check backtest job status."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{DEFAULT_URL}/backtest/{run_id}/status")
    typer.echo(resp.text)
    raise typer.Exit(code=0 if resp.is_success else 1)


@app.command("results")
def backtest_results(run_id: str = typer.Argument(...)) -> None:
    """Download backtest results."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{DEFAULT_URL}/backtest/{run_id}/results")
    typer.echo(resp.text)
    raise typer.Exit(code=0 if resp.is_success else 1)
