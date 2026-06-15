"""``tb instrument`` — universe instrument management."""

from __future__ import annotations

import asyncio

import typer

from tb.lib.db import async_connect

app = typer.Typer(no_args_is_help=True, help="Instrument universe management")


@app.command("list")
def instrument_list(
    active_only: bool = typer.Option(True, "--active/--all"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List instruments."""

    async def _run() -> None:
        async with async_connect() as conn:
            if active_only:
                rows = await conn.fetch(
                    """
                    SELECT id, symbol, active FROM theeyebeta.instruments
                     WHERE active
                     ORDER BY symbol LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, symbol, active FROM theeyebeta.instruments
                     ORDER BY symbol LIMIT $1
                    """,
                    limit,
                )
        for row in rows:
            flag = "Y" if row["active"] else "N"
            typer.echo(f"{row['symbol']:<8} id={row['id']} active={flag}")

    asyncio.run(_run())


@app.command("add")
def instrument_add(
    tickers: list[str] = typer.Argument(..., help="Symbols to add"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Add tickers to universe (requires exchange mapping)."""
    typer.echo(f"Would add {len(tickers)} tickers: {', '.join(tickers)}")
    if dry_run:
        return
    typer.echo("Use scripts/select_universe_by_cap.py or manual SQL for new listings.", err=True)
    raise typer.Exit(code=1)


@app.command("remove")
def instrument_remove(
    tickers: list[str] = typer.Argument(...),
    hard_delete: bool = typer.Option(False, "--hard-delete"),
) -> None:
    """Deactivate instruments."""

    async def _run() -> None:
        async with async_connect() as conn:
            for symbol in tickers:
                if hard_delete:
                    typer.echo(f"hard delete not supported for {symbol}")
                    continue
                await conn.execute(
                    "UPDATE theeyebeta.instruments SET active=false WHERE UPPER(symbol)=UPPER($1)",
                    symbol,
                )
                typer.echo(f"deactivated {symbol}")

    asyncio.run(_run())
