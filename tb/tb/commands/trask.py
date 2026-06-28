"""``tb trask`` — audit & monitoring (tb trask commands)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.live import Live
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
from tb.lib.trask_workers import resolve_worker_unit

load_dotenv()

app = typer.Typer(
    no_args_is_help=True, help="Trask worker registry and circuit breakers"
)

LOCAL_ROOT = Path(
    os.environ.get("THEEYE_LOCAL_ROOT", "/home/the-eye-beta/TheEyeBeta2025/TheEyeProd")
)
LOCAL_THEEYE = LOCAL_ROOT / "theeye"


def _systemctl(action: str, unit: str, *, confirm: bool) -> None:
    if action != "status" and not confirm:
        if not typer.confirm(f"Run systemctl {action} {unit}?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
    proc = subprocess.run(  # noqa: S603
        ["systemctl", action, unit],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.stdout.strip():
        typer.echo(proc.stdout.strip())
    if proc.stderr.strip():
        typer.echo(proc.stderr.strip(), err=True)
    raise typer.Exit(code=proc.returncode)


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
    refresh: float = typer.Option(
        2.0, "--refresh", "-r", help="Refresh interval (seconds)"
    ),
) -> None:
    """Live Trask component dashboard."""
    asyncio.run(_trask_dashboard_async(once=once, refresh=refresh))


@app.command("events")
def trask_events(
    limit: int = typer.Option(20, "--limit"),
    severity: str | None = typer.Option(None, "--severity", help="Filter by severity"),
    event_type: str | None = typer.Option(None, "--type", help="Filter by alert type"),
) -> None:
    """Recent audit alerts."""
    asyncio.run(_trask_events_async(limit, severity=severity, event_type=event_type))


@app.command("findings")
def trask_findings(limit: int = typer.Option(20, "--limit")) -> None:
    """Open data gap findings."""
    asyncio.run(_trask_findings_async(limit))


@app.command("audit")
def trask_audit(limit: int = typer.Option(20, "--limit")) -> None:
    """Recent worker run audit rows."""
    asyncio.run(_trask_audit_async(limit))


@app.command("digest")
def trask_digest(
    now: bool = typer.Option(False, "--now", help="Trigger digest email immediately"),
) -> None:
    """View digest status or trigger digest via the configured Trask command."""
    if LOCAL_THEEYE.is_file() and os.access(LOCAL_THEEYE, os.X_OK):
        cmd = [str(LOCAL_THEEYE), "trask", "digest"]
        if now:
            cmd.append("--now")
        proc = subprocess.run(cmd, check=False)  # noqa: S603
        raise typer.Exit(code=proc.returncode)
    if now:
        typer.echo(
            "Digest trigger requires the Trask command (set THEEYE_LOCAL_ROOT).",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo("Trask digest status: use `tb trask digest --now`")


worker_app = typer.Typer(no_args_is_help=True, help="Worker control")
sentinel_app = typer.Typer(no_args_is_help=True, help="Sentinel control")
app.add_typer(worker_app, name="worker")
app.add_typer(sentinel_app, name="sentinel")


@worker_app.callback(invoke_without_command=True)
def worker_control(
    ctx: typer.Context,
    action: str = typer.Argument("status", help="status|start|stop|restart"),
    worker_id: str | None = typer.Argument(None, help="Component id"),
    confirm: bool = typer.Option(False, "--confirm", help="Skip confirmation prompt"),
) -> None:
    """Control prod workers via systemd (maps Trask ids to theeye units)."""
    if ctx.invoked_subcommand is not None:
        return
    if action == "status":
        asyncio.run(_component_status_async(worker_id, component_type="worker"))
        return
    if not worker_id:
        typer.echo("Worker id required for start/stop/restart", err=True)
        raise typer.Exit(code=1)
    unit = resolve_worker_unit(worker_id)
    if not unit:
        if LOCAL_THEEYE.is_file():
            cmd = [str(LOCAL_THEEYE), "trask", "worker", action, worker_id]
            if confirm:
                cmd.append("--confirm")
            proc = subprocess.run(cmd, check=False)  # noqa: S603
            raise typer.Exit(code=proc.returncode)
        typer.echo(f"Unknown worker id: {worker_id}", err=True)
        raise typer.Exit(code=1)
    _systemctl(action, unit, confirm=confirm)


@sentinel_app.callback(invoke_without_command=True)
def sentinel_control(
    ctx: typer.Context,
    action: str = typer.Argument("status", help="status|start|stop|restart"),
    sentinel_id: str | None = typer.Argument(None, help="Component id"),
    confirm: bool = typer.Option(False, "--confirm", help="Skip confirmation prompt"),
) -> None:
    """Sentinel status (control delegated to Local Trask IPC when needed)."""
    if ctx.invoked_subcommand is not None:
        return
    if action == "status":
        asyncio.run(_component_status_async(sentinel_id, component_type="sentinel"))
        return
    if LOCAL_THEEYE.is_file():
        cmd = [str(LOCAL_THEEYE), "trask", "sentinel", action]
        if sentinel_id:
            cmd.append(sentinel_id)
        if confirm:
            cmd.append("--confirm")
        proc = subprocess.run(cmd, check=False)  # noqa: S603
        raise typer.Exit(code=proc.returncode)
    typer.echo("Sentinel control requires Local Trask.", err=True)
    raise typer.Exit(code=1)


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


async def _trask_dashboard_async(*, once: bool, refresh: float) -> None:
    async def _build() -> Table:
        async with async_connect() as conn:
            rows = await fetch_trask_components(conn)
            breakers = await fetch_open_breakers(conn)
        table = Table(
            title=f"Trask Dashboard — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        table.add_column("Component")
        table.add_column("Type")
        table.add_column("State")
        table.add_column("Age(s)")
        now = datetime.now(UTC)
        for row in rows:
            hb = row["last_heartbeat"]
            age = int((now - hb).total_seconds()) if hb else 9999
            table.add_row(
                str(row["component_id"]),
                str(row["component_type"]),
                str(row["state"]),
                str(age),
            )
        table.caption = f"Open breakers: {len(breakers)}"
        return table

    if once:
        console.print(await _build())
        return

    with Live(console=console, refresh_per_second=4) as live:
        try:
            while True:
                live.update(await _build())
                time.sleep(max(refresh, 0.5))
        except KeyboardInterrupt:
            typer.echo("\nDashboard stopped.")


async def _trask_events_async(
    limit: int,
    *,
    severity: str | None = None,
    event_type: str | None = None,
) -> None:
    async with async_connect() as conn:
        alerts = await fetch_audit_alerts(
            conn, limit=limit, severity=severity, alert_type=event_type
        )
    for alert in alerts:
        worker = alert.get("worker_name") or "system"
        typer.echo(
            f"{alert['created_at']} [{alert['severity']}] {worker}: {alert['message']}",
        )


async def _trask_findings_async(limit: int) -> None:
    async with async_connect() as conn:
        gaps = await fetch_data_gaps(conn, limit=limit)
    for gap in gaps:
        typer.echo(
            f"inst={gap.get('instrument_id')} {gap.get('dataset_type')} {gap['severity']} "
            f"{gap.get('gap_start')}..{gap.get('gap_end')}",
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
    if not rows:
        typer.echo(f"No {component_type} components found")
        return
    for row in rows:
        typer.echo(f"{row['component_id']}: {row['state']} hb={row['last_heartbeat']}")
