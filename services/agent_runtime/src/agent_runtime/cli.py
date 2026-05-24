"""tb-agent CLI — run agents against market snapshots."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import typer
from dotenv import load_dotenv

from .runner import run_agent

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="theeyebeta agent runtime")


@app.command("version")
def version_cmd() -> None:
    """Print agent-runtime version."""
    typer.echo("agent-runtime 0.1.0")


@app.command("run")
def run(
    agent_id: str = typer.Argument(..., help="Agent id (e.g. technical-analyst)"),
    market: str = typer.Option(..., help="MIC exchange code (e.g. XNAS)"),
    target_date: str = typer.Option(..., "--date", help="Trade date YYYY-MM-DD"),
) -> None:
    """Run one agent against a market snapshot for the given date."""
    out = asyncio.run(run_agent(agent_id, market, date.fromisoformat(target_date)))
    typer.echo(json.dumps(out, indent=2))
