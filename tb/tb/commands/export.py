"""``tb export`` — export canonical data."""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import fetch_price_series, resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Export canonical data")


@app.command("prices")
def export_prices(
    symbol: str = typer.Argument(...),
    output: Path | None = typer.Option(None, "--output", "-o"),
    fmt: str = typer.Option("csv", "--format", help="csv or json"),
) -> None:
    """Export daily prices for a symbol."""

    async def _run() -> list[dict[str, object]]:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            return await fetch_price_series(conn, int(inst["instrument_id"]), limit=5000)

    rows = asyncio.run(_run())
    out = output.open("w", newline="") if output else sys.stdout
    try:
        if fmt == "json":
            json.dump(rows, out, indent=2, default=str)
        else:
            writer = csv.DictWriter(out, fieldnames=["d", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in writer.fieldnames})
    finally:
        if output:
            out.close()


@app.command("schema")
def export_schema(output: Path | None = typer.Option(None, "--output", "-o")) -> None:
    """Export theeyebeta table list."""

    async def _run() -> list[str]:
        async with async_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name FROM information_schema.tables
                 WHERE table_schema = 'theeyebeta' ORDER BY table_name
                """,
            )
        return [r["table_name"] for r in rows]

    tables = asyncio.run(_run())
    text = "\n".join(tables)
    if output:
        output.write_text(text + "\n")
    else:
        typer.echo(text)
