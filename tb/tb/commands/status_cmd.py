"""``tb status`` — platform and service health."""

from __future__ import annotations

import asyncio
import json
import subprocess

import typer
from dotenv import load_dotenv
from rich.table import Table

from tb.lib.console import console
from tb.lib.db import async_connect
from tb.lib.queries.platform import fetch_platform_summary
from tb.lib.systemd import list_timers

load_dotenv()

app = typer.Typer(help="Platform health summary")


def _docker_health() -> list[dict[str, str]]:
    try:
        proc = subprocess.run(  # noqa: S603, S607
            ["docker", "compose", "ps", "--format", "{{.Name}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError:
        return []
    rows: list[dict[str, str]] = []
    for line in proc.stdout.splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            health = (
                "green"
                if "healthy" in status.lower() or "up" in status.lower()
                else "yellow"
            )
            if "exited" in status.lower() or "dead" in status.lower():
                health = "red"
            rows.append({"name": name, "status": status, "health": health})
    return rows


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context, json_output: bool = typer.Option(False, "--json")
) -> None:
    """Show universe counts, Docker health, price freshness, and timers."""
    if ctx.invoked_subcommand is not None:
        return

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_platform_summary(conn)

    summary = asyncio.run(_run())
    docker = _docker_health()
    payload = {**summary, "docker_services": docker, "timers": list_timers()}
    if json_output:
        typer.echo(json.dumps(payload, indent=2, default=str))
        return

    typer.echo("theeyebeta platform status")
    typer.echo(f"  EOD active universe:    {summary['active_eod_universe']}")
    typer.echo(f"  Intraday eligible:      {summary['intraday_eligible']}")
    typer.echo(f"  Latest daily date:      {summary['latest_daily_date']}")
    typer.echo(f"  Latest intraday bucket: {summary['latest_intraday_ts']}")
    stale = summary["stale_heartbeats"]
    if stale:
        typer.echo(f"  Stale heartbeats (>26h): {len(stale)}")
        for row in stale[:10]:
            typer.echo(f"    - {row['worker_id']}: {row['last']}")
    else:
        typer.echo("  Worker heartbeats:      all fresh (<26h) in checked set")

    if docker:
        table = Table(title="Docker services")
        table.add_column("Service")
        table.add_column("Status")
        table.add_column("Health")
        for svc in docker[:20]:
            table.add_row(svc["name"], svc["status"], svc["health"])
        console.print(table)

    typer.echo("")
    typer.echo("systemd timers (theeye-*):")
    typer.echo(list_timers())
