"""``tb intraday`` — intraday coverage and latest bars."""

from __future__ import annotations

import asyncio
from datetime import date

import typer

from tb.lib.db import async_connect
from tb.lib.queries.platform import fetch_intraday_coverage

app = typer.Typer(no_args_is_help=True, help="Intraday bucket coverage")


@app.command("coverage")
def intraday_coverage(
    on_date: str | None = typer.Option(None, "--date", help="Bucket date YYYY-MM-DD"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    """Show latest intraday bucket fill rate vs eligible universe."""
    bucket = date.fromisoformat(on_date) if on_date else None

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_intraday_coverage(conn, bucket_date=bucket)

    summary = asyncio.run(_run())
    if json_output:
        import json

        typer.echo(json.dumps(summary, indent=2))
        return
    typer.echo(f"Intraday coverage ({summary['bucket_date']})")
    typer.echo(f"  Latest bucket:  {summary['bucket_ts']}")
    typer.echo(f"  Eligible:       {summary['eligible']}")
    typer.echo(f"  Filled:         {summary['filled']}")
    typer.echo(f"  Coverage:       {summary['coverage_pct']}%")


@app.command("latest")
def intraday_latest(
    symbol: str | None = typer.Option(None, "--symbol", "-s", help="Filter by symbol"),
    limit: int = typer.Option(10, "--limit", help="Rows to show"),
) -> None:
    """Show most recent intraday bars."""

    async def _run() -> None:
        async with async_connect() as conn:
            if symbol:
                inst = await conn.fetchrow(
                    "SELECT id FROM theeyebeta.instruments WHERE UPPER(symbol)=UPPER($1)",
                    symbol,
                )
                if not inst:
                    typer.echo(f"Unknown symbol {symbol}", err=True)
                    raise typer.Exit(code=1)
                rows = await conn.fetch(
                    """
                    SELECT i.symbol, p.ts, p.close, p.volume
                      FROM theeyebeta.prices_intraday p
                      JOIN theeyebeta.instruments i ON i.id = p.instrument_id
                     WHERE p.instrument_id = $1
                     ORDER BY p.ts DESC
                     LIMIT $2
                    """,
                    inst["id"],
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT i.symbol, p.ts, p.close, p.volume
                      FROM theeyebeta.prices_intraday p
                      JOIN theeyebeta.instruments i ON i.id = p.instrument_id
                     ORDER BY p.ts DESC
                     LIMIT $1
                    """,
                    limit,
                )
        for row in rows:
            typer.echo(
                f"{row['ts']}  {row['symbol']:<8} close={row['close']} vol={row['volume']}"
            )

    asyncio.run(_run())
