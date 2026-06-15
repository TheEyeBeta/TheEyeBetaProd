"""``tb canonical`` — canonical data freshness and gaps."""

from __future__ import annotations

import asyncio
import json

import typer

from tb.lib.db import async_connect
from tb.lib.queries.platform import fetch_canonical_status
from tb.lib.queries.trask import fetch_data_gaps

app = typer.Typer(no_args_is_help=True, help="Canonical prices and indicators status")


@app.command("status")
def canonical_status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Prices and indicators freshness vs active universe."""

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_canonical_status(conn)

    summary = asyncio.run(_run())
    if json_output:
        typer.echo(json.dumps(summary, indent=2))
        return
    typer.echo("Canonical data status")
    typer.echo(f"  Latest daily date:     {summary['latest_daily_date']}")
    typer.echo(f"  Active universe:       {summary['active_universe']}")
    typer.echo(
        f"  Price instruments:     {summary['price_instruments']} "
        f"({summary['price_coverage_pct']}%)",
    )
    typer.echo(
        f"  Indicator rows:        {summary['indicator_rows']} "
        f"({summary['indicator_coverage_pct']}% )"
        if summary["indicator_coverage_pct"] is not None
        else "  Indicator rows:        (no SELECT grant on ind_technical_daily)",
    )


@app.command("gaps")
def canonical_gaps(
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Open instrument-scoped data gaps."""

    async def _run() -> list[dict[str, object]]:
        async with async_connect() as conn:
            return await fetch_data_gaps(conn, open_only=True, limit=limit)

    gaps = asyncio.run(_run())
    if json_output:
        typer.echo(json.dumps(gaps, indent=2, default=str))
        return
    typer.echo(f"Open data gaps ({len(gaps)} shown)")
    for gap in gaps:
        typer.echo(
            f"  id={gap['id']} inst={gap['instrument_id']} {gap['gap_type']} "
            f"{gap['severity']} {gap['gap_start']}..{gap['gap_end']}",
        )
