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
    agent_id: str = typer.Argument(..., help="Agent id (e.g. macro-lead)"),
    snapshot_id: str | None = typer.Option(
        None,
        "--snapshot-id",
        help="Packaged snapshot UUID (preferred)",
    ),
    market: str | None = typer.Option(None, help="Market code when resolving by date"),
    target_date: str | None = typer.Option(None, "--date", help="Trade date YYYY-MM-DD"),
) -> None:
    """Run one agent against a packaged snapshot."""
    if snapshot_id:
        from uuid import UUID

        from .runner import AgentRunner

        out = asyncio.run(AgentRunner().run(agent_id, UUID(snapshot_id)))
    else:
        if not market or not target_date:
            raise typer.BadParameter("Provide --snapshot-id or both --market and --date")
        out = asyncio.run(run_agent(agent_id, market, date.fromisoformat(target_date)))
    typer.echo(json.dumps(out, indent=2))
