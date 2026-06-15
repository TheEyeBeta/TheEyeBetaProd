"""``tb snapshot`` — packaged snapshot queries."""

from __future__ import annotations

import asyncio
import json

import typer

from tb.lib.db import async_connect

app = typer.Typer(no_args_is_help=True, help="Packaged data snapshots")


@app.command("quote")
def snapshot_quote(symbol: str = typer.Argument(...)) -> None:
    """Quick quote from latest daily price."""
    from tb.commands.now import now_price

    now_price(symbol)


@app.command("get")
def snapshot_get(
    symbol: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Full snapshot row from data_snapshots if present."""

    async def _run() -> dict[str, object] | None:
        async with async_connect() as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot_id, market, as_of, payload
                  FROM theeyebeta.data_snapshots
                 WHERE payload::text ILIKE $1
                 ORDER BY as_of DESC
                 LIMIT 1
                """,
                f"%{symbol.upper()}%",
            )
        return dict(row) if row else None

    row = asyncio.run(_run())
    if not row:
        typer.echo("No snapshot found", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(row, indent=2, default=str))
    else:
        typer.echo(
            f"snapshot {row['snapshot_id']} market={row['market']} as_of={row['as_of']}"
        )


@app.command("movers")
def snapshot_movers(limit: int = typer.Option(10, "--limit")) -> None:
    """Top daily movers from prices."""
    from tb.commands.returns import returns_leaderboard

    returns_leaderboard(window=1, limit=limit)
