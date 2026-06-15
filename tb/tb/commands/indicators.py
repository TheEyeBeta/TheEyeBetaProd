"""``tb indicators`` — technical indicator queries and compute."""

from __future__ import annotations

import asyncio
import subprocess

import typer

from tb.lib.db import async_connect
from tb.lib.paths import REPO_ROOT
from tb.lib.queries.instruments import fetch_latest_indicators, resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Technical indicators")


@app.command("latest")
def indicators_latest(symbol: str = typer.Argument(...)) -> None:
    """Latest indicators for a symbol."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            ind = await fetch_latest_indicators(conn, int(inst["instrument_id"]))
        if not ind:
            typer.echo("No indicators", err=True)
            raise typer.Exit(code=1)
        for key, val in ind.items():
            if val is not None:
                typer.echo(f"{key}: {val}")

    asyncio.run(_run())


@app.command("compute")
def indicators_compute(
    on_date: str | None = typer.Option(None, "--date"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run IndicatorComputeWorker."""
    cmd = ["uv", "run", "python", "-m", "workers.indicator_compute_worker", "--run-type", "manual"]
    if on_date:
        cmd.extend(["--date", on_date])
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)


@app.command("null-report")
def indicators_null_report(on_date: str | None = typer.Option(None, "--date")) -> None:
    """Count active instruments missing indicators on a date."""

    async def _run() -> None:
        async with async_connect() as conn:
            d = on_date or str(
                await conn.fetchval("SELECT MAX(date) FROM theeyebeta.ind_technical_daily")
            )
            missing = await conn.fetchval(
                """
                SELECT COUNT(*) FROM theeyebeta.instruments i
                 WHERE i.active
                   AND NOT EXISTS (
                       SELECT 1 FROM theeyebeta.ind_technical_daily t
                        WHERE t.instrument_id = i.id AND t.date = $1::date
                   )
                """,
                d,
            )
        typer.echo(f"date={d} missing_indicators={missing}")

    asyncio.run(_run())
