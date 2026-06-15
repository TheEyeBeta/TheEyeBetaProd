"""``tb signals`` — trading signal queries."""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="Trading signals")


@app.command("latest")
def signals_latest(
    symbol: str = typer.Argument(...), limit: int = typer.Option(5, "--limit")
) -> None:
    """Latest signals for a symbol."""
    typer.echo(f"Signals for {symbol} — served by agent-runtime (limit={limit})")


@app.command("scan")
def signals_scan(on_date: str = typer.Option(..., "--date")) -> None:
    """Scan signals on a date."""
    typer.echo(f"Signal scan for {on_date} — use master-orchestrator when deployed")
