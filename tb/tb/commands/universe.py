"""``tb universe`` — tier selection and instrument management."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import search_instruments
from tb.lib.queries.platform import fetch_platform_summary

app = typer.Typer(no_args_is_help=True, help="Universe tier management")

ROOT = Path(__file__).resolve().parents[3]


@app.command("sync")
def universe_sync(
    tier: str = typer.Option("eod", "--tier", help="eod or intraday"),
    apply: bool = typer.Option(
        False, "--apply", help="Write instruments.active (eod only)"
    ),
    date: str | None = typer.Option(None, "--date", help="Cap as-of date YYYY-MM-DD"),
) -> None:
    """Select universe tier from market-cap snapshots."""
    if tier not in {"eod", "intraday"}:
        typer.echo("--tier must be eod or intraday", err=True)
        raise typer.Exit(code=1)
    cmd = ["uv", "run", "python", "scripts/select_universe_by_cap.py", "--tier", tier]
    if apply:
        if tier != "eod":
            typer.echo("--apply only valid for --tier eod", err=True)
            raise typer.Exit(code=1)
        cmd.append("--apply")
    if date:
        cmd.extend(["--date", date])
    proc = subprocess.run(cmd, cwd=ROOT, check=False)  # noqa: S603
    raise typer.Exit(code=proc.returncode)


@app.command("tiers")
def universe_tiers() -> None:
    """EOD active vs intraday-eligible counts."""

    async def _run() -> None:
        async with async_connect() as conn:
            summary = await fetch_platform_summary(conn)
            cap_date = await conn.fetchval(
                "SELECT MAX(as_of_date) FROM theeyebeta.market_cap_daily"
            )
        typer.echo(f"Cap snapshot date: {cap_date}")
        typer.echo(f"EOD active:        {summary['active_eod_universe']}")
        typer.echo(f"Intraday eligible: {summary['intraday_eligible']}")

    asyncio.run(_run())


@app.command("list")
def universe_list(
    active_only: bool = typer.Option(True, "--active/--all"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List universe instruments."""

    async def _run() -> None:
        async with async_connect() as conn:
            if active_only:
                rows = await conn.fetch(
                    """
                    SELECT symbol, active FROM theeyebeta.instruments
                     WHERE active
                     ORDER BY symbol LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT symbol, active FROM theeyebeta.instruments
                     ORDER BY symbol LIMIT $1
                    """,
                    limit,
                )
        for row in rows:
            typer.echo(f"{row['symbol']:<8} active={row['active']}")

    asyncio.run(_run())


@app.command("search")
def universe_search(
    query: str = typer.Argument(...), limit: int = typer.Option(20, "--limit")
) -> None:
    """Search instruments by symbol prefix."""

    async def _run() -> None:
        async with async_connect() as conn:
            rows = await search_instruments(conn, query, limit=limit)
        for row in rows:
            typer.echo(f"{row['symbol']:<8} id={row['id']} active={row['active']}")

    asyncio.run(_run())


@app.command("coverage")
def universe_coverage() -> None:
    """Data coverage for active universe."""
    import asyncio

    from tb.lib.db import async_connect
    from tb.lib.queries.platform import fetch_canonical_status

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_canonical_status(conn)

    summary = asyncio.run(_run())
    typer.echo(f"Latest daily: {summary['latest_daily_date']}")
    typer.echo(f"Price coverage: {summary['price_coverage_pct']}%")
