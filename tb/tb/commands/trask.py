"""``tb trask`` — worker registry, dashboard, and audit."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import typer
from dotenv import load_dotenv
from rich.table import Table

from tb.lib.console import console
from tb.lib.db import async_connect
from tb.lib.queries.trask import (
    fetch_audit_alerts,
    fetch_data_gaps,
    fetch_open_breakers,
    fetch_trask_components,
    fetch_worker_runs,
)

load_dotenv()

app = typer.Typer(
    no_args_is_help=True, help="Trask worker registry and circuit breakers"
)


@app.command("status")
def trask_status() -> None:
    """Show component states and open circuit breakers."""
    asyncio.run(_trask_status_async())


@app.command("workers")
def trask_workers() -> None:
    """List all registered Trask components."""
    asyncio.run(_trask_workers_async())


@app.command("dashboard")
def trask_dashboard(
    once: bool = typer.Option(False, "--once", help="Print once and exit"),
    refresh: int = typer.Option(
        5, "--refresh", help="Refresh seconds (ignored with --once)"
    ),
) -> None:
    """Live Trask component dashboard."""
    _ = refresh
    asyncio.run(_trask_dashboard_async())


@app.command("events")
def trask_events(limit: int = typer.Option(20, "--limit")) -> None:
    """Recent audit alerts."""
    asyncio.run(_trask_events_async(limit))


@app.command("findings")
def trask_findings(limit: int = typer.Option(20, "--limit")) -> None:
    """Open data gap findings."""
    asyncio.run(_trask_findings_async(limit))


@app.command("audit")
def trask_audit(limit: int = typer.Option(20, "--limit")) -> None:
    """Recent worker run audit rows."""
    asyncio.run(_trask_audit_async(limit))


worker_app = typer.Typer(no_args_is_help=True, help="Worker control (read-only status)")
sentinel_app = typer.Typer(
    no_args_is_help=True, help="Sentinel control (read-only status)"
)
app.add_typer(worker_app, name="worker")
app.add_typer(sentinel_app, name="sentinel")


@worker_app.callback(invoke_without_command=True)
def worker_control(
    ctx: typer.Context,
    action: str = typer.Argument("status", help="status|start|stop|restart"),
    worker_id: str | None = typer.Argument(None, help="Component id"),
) -> None:
    """Worker control — status is read-only; mutations via systemd."""
    if ctx.invoked_subcommand is not None:
        return
    if action != "status":
        typer.echo(
            f"Use systemd for {action}: systemctl {action} theeye-<worker>.service",
            err=True,
        )
        raise typer.Exit(code=1)
    asyncio.run(_component_status_async(worker_id, component_type="worker"))


@sentinel_app.callback(invoke_without_command=True)
def sentinel_control(
    ctx: typer.Context,
    action: str = typer.Argument("status", help="status|start|stop|restart"),
    sentinel_id: str | None = typer.Argument(None, help="Component id"),
) -> None:
    """Sentinel control — status is read-only."""
    if ctx.invoked_subcommand is not None:
        return
    if action != "status":
        typer.echo(f"Use systemd for {action} on sentinel units.", err=True)
        raise typer.Exit(code=1)
    asyncio.run(_component_status_async(sentinel_id, component_type="sentinel"))


async def _trask_status_async() -> None:
    async with async_connect() as conn:
        open_breakers = await fetch_open_breakers(conn)
        failed = await conn.fetch(
            """
            SELECT component_id, display_name, state, last_heartbeat
              FROM theeyebeta.trask_components
             WHERE state = 'FAILED'
             ORDER BY component_id
            """,
        )
    typer.echo(f"Open circuit breakers: {len(open_breakers)}")
    for row in open_breakers:
        typer.echo(
            f"  {row['component_id']}: failures={row['failure_count']} opened={row['opened_at']}",
        )
    typer.echo(f"FAILED components: {len(failed)}")
    for row in failed:
        typer.echo(
            f"  {row['component_id']} ({row['display_name']}): hb={row['last_heartbeat']}"
        )
    if not open_breakers and not failed:
        typer.echo("All Trask components healthy (no open breakers or FAILED state).")


async def _trask_workers_async() -> None:
    async with async_connect() as conn:
        rows = await fetch_trask_components(conn)
    table = Table(title="Trask components")
    table.add_column("TYPE")
    table.add_column("ID")
    table.add_column("STATE")
    table.add_column("HEARTBEAT")
    for row in rows:
        hb = row["last_heartbeat"]
        table.add_row(
            str(row["component_type"]),
            str(row["component_id"]),
            str(row["state"]),
            hb.isoformat() if hb else "never",
        )
    console.print(table)


async def _trask_dashboard_async() -> None:
    async with async_connect() as conn:
        rows = await fetch_trask_components(conn)
        breakers = await fetch_open_breakers(conn)
    table = Table(title="Trask Dashboard")
    table.add_column("Component")
    table.add_column("State")
    table.add_column("Age(s)")
    now = datetime.now(UTC)
    for row in rows:
        hb = row["last_heartbeat"]
        age = int((now - hb).total_seconds()) if hb else 9999
        table.add_row(str(row["component_id"]), str(row["state"]), str(age))
    console.print(table)
    console.print(f"Open breakers: {len(breakers)}")


async def _trask_events_async(limit: int) -> None:
    async with async_connect() as conn:
        alerts = await fetch_audit_alerts(conn, limit=limit)
    for alert in alerts:
        typer.echo(
            f"{alert['created_at']} [{alert['severity']}] {alert['worker_id']}: {alert['message']}",
        )


async def _trask_findings_async(limit: int) -> None:
    async with async_connect() as conn:
        gaps = await fetch_data_gaps(conn, limit=limit)
    for gap in gaps:
        typer.echo(
            f"inst={gap['instrument_id']} {gap['gap_type']} {gap['severity']} "
            f"{gap['gap_start']}..{gap['gap_end']}",
        )


async def _trask_audit_async(limit: int) -> None:
    async with async_connect() as conn:
        runs = await fetch_worker_runs(conn, limit=limit)
    for run in runs:
        typer.echo(
            f"{run['worker_name']} {run['trade_date']} {run['status']} started={run['started_at']}",
        )


async def _component_status_async(
    component_id: str | None, *, component_type: str
) -> None:
    async with async_connect() as conn:
        if component_id:
            row = await conn.fetchrow(
                """
                SELECT * FROM theeyebeta.trask_components
                 WHERE component_id = $1 AND component_type = $2
                """,
                component_id,
                component_type,
            )
            rows = [row] if row else []
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM theeyebeta.trask_components
                 WHERE component_type = $1 ORDER BY component_id
                """,
                component_type,
            )
    for row in rows:
        typer.echo(f"{row['component_id']}: {row['state']} hb={row['last_heartbeat']}")
