"""``tb prices`` — price data inspection and ingestion triggers."""

from __future__ import annotations

import asyncio
import subprocess

import typer

from tb.lib.db import async_connect
from tb.lib.paths import REPO_ROOT
from tb.lib.queries.instruments import fetch_price_series, resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Canonical price data")


@app.command("freshness")
def prices_freshness() -> None:
    """Latest daily price date and row count."""

    async def _run() -> None:
        async with async_connect() as conn:
            latest = await conn.fetchval(
                "SELECT MAX(ts::date) FROM theeyebeta.prices_daily"
            )
            count = await conn.fetchval("SELECT COUNT(*) FROM theeyebeta.prices_daily")
        typer.echo(f"latest={latest} total_rows={count:,}")

    asyncio.run(_run())


@app.command("range")
def prices_range(
    symbol: str = typer.Argument(...),
    start: str | None = typer.Option(None, "--start"),
    end: str | None = typer.Option(None, "--end"),
) -> None:
    """Show price date range for a symbol."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            row = await conn.fetchrow(
                """
                SELECT MIN(ts::date) AS mn, MAX(ts::date) AS mx, COUNT(*) AS c
                  FROM theeyebeta.prices_daily WHERE instrument_id=$1
                """,
                inst["instrument_id"],
            )
        typer.echo(f"{symbol}: {row['mn']} .. {row['mx']} ({row['c']} bars)")

    asyncio.run(_run())


@app.command("sample")
def prices_sample(
    symbol: str = typer.Argument(...), limit: int = typer.Option(10, "--limit")
) -> None:
    """Sample recent daily bars."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            rows = await fetch_price_series(
                conn, int(inst["instrument_id"]), limit=limit
            )
        for row in rows[-limit:]:
            typer.echo(f"{row['d']} close={row['close']}")

    asyncio.run(_run())


@app.command("ingest")
def prices_ingest(
    on_date: str | None = typer.Option(None, "--date"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Trigger Massive EOD ingestion worker."""
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "workers.massive_ingestion_worker",
        "--run-type",
        "manual",
    ]
    if on_date:
        cmd.extend(["--date", on_date])
    if dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)


gaps_app = typer.Typer(help="Price gap detection")
app.add_typer(gaps_app, name="gaps")


@gaps_app.command("detect")
def gaps_detect(on_date: str | None = typer.Option(None, "--date")) -> None:
    """Run gap sentinel (detect mode)."""
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "workers.gap_sentinel_worker",
        "--run-type",
        "manual",
    ]
    if on_date:
        cmd.extend(["--date", on_date])
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)
