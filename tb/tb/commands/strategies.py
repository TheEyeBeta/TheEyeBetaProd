"""``tb strategies`` and ``tb signals`` — strategy stubs."""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="Strategy definitions")


@app.command("list")
def strategies_list() -> None:
    """List registered strategies."""
    typer.echo(
        "(strategies served by agent-runtime — query via admin API when deployed)"
    )


@app.command("describe")
def strategies_describe(name: str = typer.Argument(...)) -> None:
    """Describe one strategy."""
    typer.echo(f"Strategy {name}: not loaded in CLI — use admin-service")
