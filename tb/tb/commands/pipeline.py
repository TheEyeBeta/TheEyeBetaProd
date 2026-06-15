"""``tb pipeline`` — daily pipeline orchestration."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date

import typer

from tb.lib.db import async_connect
from tb.lib.paths import REPO_ROOT

app = typer.Typer(no_args_is_help=True, help="Daily pipeline control")


@app.command("daily")
def pipeline_daily(
    on_date: str | None = typer.Option(None, "--date"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    run_type: str = typer.Option("manual", "--run-type"),
) -> None:
    """Run the canonical daily pipeline."""
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "workers.daily_pipeline_runner",
        "--run-type",
        run_type,
    ]
    if on_date:
        cmd.extend(["--date", on_date])
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)


@app.command("status")
def pipeline_status(limit: int = typer.Option(10, "--limit")) -> None:
    """Recent daily_pipeline worker runs."""

    async def _run() -> None:
        async with async_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT trade_date, status, started_at, ended_at, metadata
                  FROM theeyebeta.worker_runs
                 WHERE worker_name = 'daily_pipeline'
                 ORDER BY started_at DESC
                 LIMIT $1
                """,
                limit,
            )
        for row in rows:
            typer.echo(f"{row['trade_date']} {row['status']} {row['started_at']}")

    asyncio.run(_run())


@app.command("dry-run")
def pipeline_dry_run(on_date: str | None = typer.Option(None, "--date")) -> None:
    """Preview pipeline actions."""
    pipeline_daily(on_date=on_date, dry_run=True, run_type="manual")


@app.command("report")
def pipeline_report(
    on_date: str = typer.Argument(..., help="Trade date YYYY-MM-DD"),
) -> None:
    """Summary counts for a pipeline date."""
    trade = date.fromisoformat(on_date)

    async def _run() -> None:
        async with async_connect() as conn:
            prices = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT instrument_id)
                  FROM theeyebeta.prices_daily WHERE ts::date = $1
                """,
                trade,
            )
            inds = await conn.fetchval(
                "SELECT COUNT(*) FROM theeyebeta.ind_technical_daily WHERE date = $1",
                trade,
            )
        typer.echo(f"Pipeline report {trade}: prices={prices} indicators={inds}")

    asyncio.run(_run())
