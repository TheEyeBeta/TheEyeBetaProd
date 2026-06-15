"""``tb db`` — database maintenance and inspection."""

from __future__ import annotations

import subprocess

import typer
from dotenv import load_dotenv

from tb.lib.db import database_url, sync_connect
from tb.lib.paths import REPO_ROOT

load_dotenv()

app = typer.Typer(no_args_is_help=True, help="Database maintenance")


@app.command("migrate")
def db_migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show pending only"),
    prod: bool = typer.Option(False, "--prod", help="Confirm production migration"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation for --prod"),
) -> None:
    """Run Alembic migrations (``make db-migrate``)."""
    if dry_run:
        proc = subprocess.run(  # noqa: S603, S607
            ["uv", "run", "python", "scripts/list_pending_migrations.py"],
            cwd=REPO_ROOT,
            check=False,
        )
        raise typer.Exit(code=proc.returncode)
    if prod and not yes:
        typer.echo("This will run migrations against the configured DATABASE_URL.")
        if not typer.confirm("Migrate production?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)
    proc = subprocess.run(["make", "db-migrate"], cwd=REPO_ROOT, check=False)  # noqa: S603, S607
    raise typer.Exit(code=proc.returncode)


@app.command("shell")
def db_shell() -> None:
    """Open psql using DATABASE_URL."""
    dsn = database_url()
    proc = subprocess.run(["psql", dsn], check=False)  # noqa: S603, S607
    raise typer.Exit(code=proc.returncode)


@app.command("ping")
def db_ping() -> None:
    """Verify database connectivity."""
    with sync_connect() as conn:
        row = conn.execute("SELECT current_database(), current_user, version()").fetchone()
    typer.echo(f"database={row['current_database']} user={row['current_user']}")
    typer.echo(str(row["version"]).split(",")[0])


@app.command("verify")
def db_verify() -> None:
    """Verify core theeyebeta tables exist."""
    required = [
        "instruments",
        "prices_daily",
        "prices_intraday",
        "ind_technical_daily",
        "worker_runs",
        "worker_heartbeats",
        "trask_components",
        "trading_calendar",
        "market_cap_daily",
    ]
    missing: list[str] = []
    with sync_connect() as conn:
        for table in required:
            row = conn.execute(
                """
                SELECT 1 FROM information_schema.tables
                 WHERE table_schema = 'theeyebeta' AND table_name = %s
                """,
                (table,),
            ).fetchone()
            if not row:
                missing.append(table)
    if missing:
        typer.echo(f"Missing tables: {', '.join(missing)}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"All {len(required)} core tables present.")


@app.command("stats")
def db_stats() -> None:
    """Show row counts for major tables."""
    tables = [
        "instruments",
        "prices_daily",
        "prices_intraday",
        "ind_technical_daily",
        "worker_runs",
        "audit_data_gaps",
    ]
    with sync_connect() as conn:
        for table in tables:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM theeyebeta.{table}",  # noqa: S608
            ).fetchone()
            typer.echo(f"{table:24} {row['c']:,}")
