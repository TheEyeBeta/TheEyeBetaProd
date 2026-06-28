"""``tb instrument`` — universe instrument management."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

from tb.lib.db import async_connect

app = typer.Typer(no_args_is_help=True, help="Instrument universe management")
console = Console()

_EXCHANGE_CODES = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
}


@app.command("list")
def instrument_list(
    active_only: bool = typer.Option(True, "--active/--all"),
    limit: int = typer.Option(100, "--limit", "-n"),
) -> None:
    """List instruments."""

    async def _run() -> list[dict[str, object]]:
        async with async_connect() as conn:
            if active_only:
                rows = await conn.fetch(
                    """
                    SELECT i.id, i.symbol, i.active, e.code AS exchange
                      FROM theeyebeta.instruments i
                      JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                     WHERE i.active
                     ORDER BY i.symbol LIMIT $1
                    """,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT i.id, i.symbol, i.active, e.code AS exchange
                      FROM theeyebeta.instruments i
                      JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
                     ORDER BY i.symbol LIMIT $1
                    """,
                    limit,
                )
            return [dict(r) for r in rows]

    rows = asyncio.run(_run())
    if not rows:
        console.print("[yellow]No instruments found[/yellow]")
        return
    table = Table(title=f"Instruments ({len(rows)})")
    table.add_column("Symbol", style="cyan")
    table.add_column("Exchange")
    table.add_column("Active")
    table.add_column("ID", justify="right")
    for row in rows:
        table.add_row(
            str(row["symbol"]),
            str(row["exchange"]),
            "Y" if row["active"] else "N",
            str(row["id"]),
        )
    console.print(table)


@app.command("add")
def instrument_add(
    tickers: list[str] = typer.Argument(..., help="Symbols to add"),
    name: str | None = typer.Option(None, "--name", help="Company name"),
    exchange: str | None = typer.Option(
        None, "--exchange", "-e", help="Exchange name or code"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Add tickers to theeyebeta.instruments."""

    async def _run() -> None:
        exchange_code = _EXCHANGE_CODES.get(
            (exchange or "NASDAQ").upper(), (exchange or "XNAS").upper()
        )
        added: list[str] = []
        existing: list[str] = []

        async with async_connect() as conn:
            ex_row = await conn.fetchrow(
                "SELECT id FROM theeyebeta.exchanges WHERE code = $1 OR UPPER(name) = $2 LIMIT 1",
                exchange_code,
                (exchange or "NASDAQ").upper(),
            )
            if not ex_row:
                typer.echo(f"Exchange not found: {exchange or 'NASDAQ'}", err=True)
                raise typer.Exit(code=1)
            exchange_id = int(ex_row["id"])

            for raw in tickers:
                symbol = raw.upper()
                found = await conn.fetchval(
                    """
                    SELECT id FROM theeyebeta.instruments
                     WHERE UPPER(symbol) = $1 AND exchange_id = $2
                    """,
                    symbol,
                    exchange_id,
                )
                if found:
                    existing.append(symbol)
                    continue
                if dry_run:
                    added.append(symbol)
                    continue
                meta: dict[str, str] = {}
                if name:
                    meta["company_name"] = name
                await conn.execute(
                    """
                    INSERT INTO theeyebeta.instruments
                        (symbol, exchange_id, asset_class, active, metadata)
                    VALUES ($1, $2, 'equity', true, $3::jsonb)
                    """,
                    symbol,
                    exchange_id,
                    json.dumps(meta),
                )
                added.append(symbol)

        if added:
            console.print(f"[green]Added: {', '.join(added)}[/green]")
        if existing:
            console.print(f"[yellow]Already exists: {', '.join(existing)}[/yellow]")

    asyncio.run(_run())


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
                typer.echo(f"deactivated {symbol.upper()}")

    asyncio.run(_run())
