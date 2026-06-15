"""``tb fundamentals`` — fundamentals data (when populated)."""

from __future__ import annotations

import asyncio

import asyncpg
import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Fundamentals data")


async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1 FROM information_schema.tables
             WHERE table_schema='theeyebeta' AND table_name=$1
            """,
            table,
        ),
    )


@app.command("latest")
def fundamentals_latest(symbol: str = typer.Argument(...)) -> None:
    """Latest fundamentals row for a symbol."""

    async def _run() -> None:
        async with async_connect() as conn:
            if not await _table_exists(conn, "fundamentals"):
                typer.echo("fundamentals table not present", err=True)
                raise typer.Exit(code=1)
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            row = await conn.fetchrow(
                """
                SELECT * FROM theeyebeta.fundamentals
                 WHERE instrument_id = $1
                 ORDER BY as_of_date DESC LIMIT 1
                """,
                inst["instrument_id"],
            )
        if not row:
            typer.echo("No fundamentals")
            return
        typer.echo(dict(row))

    asyncio.run(_run())


@app.command("coverage")
def fundamentals_coverage() -> None:
    """Count instruments with fundamentals."""

    async def _run() -> None:
        async with async_connect() as conn:
            if not await _table_exists(conn, "fundamentals"):
                typer.echo("fundamentals table not present")
                return
            count = await conn.fetchval(
                "SELECT COUNT(DISTINCT instrument_id) FROM theeyebeta.fundamentals",
            )
        typer.echo(f"instruments_with_fundamentals={count}")

    asyncio.run(_run())
