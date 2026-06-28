"""``tb pipeline`` — daily pipeline orchestration (Local ``./theeye pipeline`` parity)."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date

import typer

from tb.lib.console import console
from tb.lib.db import async_connect
from tb.lib.paths import REPO_ROOT

app = typer.Typer(no_args_is_help=True, help="Daily pipeline control")

_MODE_MODULES = {
    "full": "workers.daily_pipeline_runner",
    "ingest-only": "workers.massive_ingestion_worker",
    "compute-only": "workers.indicator_compute_worker",
}


@app.command("daily")
def pipeline_daily(
    mode: str = typer.Option(
        "full",
        "--mode",
        help="Pipeline mode: full, ingest-only, or compute-only.",
    ),
    skip_non_trading: bool = typer.Option(
        False,
        "--skip-non-trading",
        help="Skip weekends/holidays (only run on trading days).",
    ),
    fail_fast: bool = typer.Option(
        False, "--fail-fast", help="Stop pipeline on first error."
    ),
    lookback: str = typer.Option("2y", "--lookback", help="Lookback window (e.g. 2y)."),
    batch_size: int = typer.Option(10, "--batch-size", help="Tickers per batch."),
    json_output: bool = typer.Option(
        False, "--json-output", help="JSON summary output."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing."),
    force_update: bool = typer.Option(
        False, "--force-update", help="Bypass market-hours check."
    ),
    post_close_delay: float = typer.Option(
        1.0, "--post-close-delay", help="Hours after market close before running."
    ),
    on_date: str | None = typer.Option(None, "--date", help="Trade date YYYY-MM-DD"),
    run_type: str = typer.Option("manual", "--run-type"),
) -> None:
    """Run the daily data pipeline."""
    if mode not in _MODE_MODULES:
        typer.echo("Invalid mode. Use: full, ingest-only, compute-only", err=True)
        raise typer.Exit(code=1)

    settings = {
        "mode": mode,
        "skip_non_trading": skip_non_trading,
        "fail_fast": fail_fast,
        "lookback": lookback,
        "batch_size": batch_size,
        "force_update": force_update,
        "post_close_delay": post_close_delay,
        "date": on_date,
    }

    if dry_run:
        console.print("DRY RUN - Would execute pipeline with settings:")
        for key, value in settings.items():
            console.print(f"  {key}: {value}")
        return

    module = _MODE_MODULES[mode]
    cmd = ["uv", "run", "python", "-m", module, "--run-type", run_type]
    if on_date:
        cmd.extend(["--date", on_date])
    if dry_run:
        cmd.append("--dry-run")
    if force_update:
        cmd.append("--force-update")
    if mode == "full":
        cmd.extend(["--mode", mode.replace("-", "_")])

    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, check=False, capture_output=True, text=True
    )  # noqa: S603
    if json_output and proc.stdout.strip():
        typer.echo(proc.stdout)
    elif proc.stdout.strip():
        typer.echo(proc.stdout)
    if proc.stderr.strip():
        typer.echo(proc.stderr, err=True)
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
