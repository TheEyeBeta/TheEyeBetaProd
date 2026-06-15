"""``tb engine`` — engine ping and status."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import typer

from tb.lib.db import async_connect

app = typer.Typer(no_args_is_help=True, help="Engine heartbeat checks")


@app.command("ping")
def engine_ping() -> None:
    """Check worker heartbeats respond."""

    async def _run() -> int:
        async with async_connect() as conn:
            fresh = await conn.fetchval(
                """
                SELECT COUNT(*) FROM theeyebeta.worker_heartbeats
                 WHERE last_heartbeat > $1
                """,
                datetime.now(UTC) - timedelta(hours=26),
            )
        return int(fresh or 0)

    count = asyncio.run(_run())
    if count:
        typer.echo(f"engine pong ({count} fresh heartbeats)")
    else:
        typer.echo("engine ping: no fresh heartbeats", err=True)
        raise typer.Exit(code=1)


@app.command("status")
def engine_status() -> None:
    """Alias for engine heartbeat summary."""
    engine_ping()
