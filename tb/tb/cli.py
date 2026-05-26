"""Root Typer application for the ``tb`` CLI."""

from __future__ import annotations

import typer

from tb.commands.snapshots import app as snapshots_app

app = typer.Typer(no_args_is_help=True, help="theeyebeta management CLI")
app.add_typer(snapshots_app, name="snapshots")


@app.command()
def status() -> None:
    """Show a short health summary (stub — extend for production hosts)."""
    typer.echo("tb status: use `docker compose ps` or service /health endpoints for now.")
