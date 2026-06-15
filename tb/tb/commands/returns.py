"""``tb returns`` — return analytics."""

from __future__ import annotations

import asyncio

import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Return analytics")


@app.command("latest")
def returns_latest(symbol: str = typer.Argument(...)) -> None:
    """Latest 1d return from daily prices."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            rows = await conn.fetch(
                """
                SELECT ts::date AS d, close,
                       LAG(close) OVER (ORDER BY ts) AS prev
                  FROM theeyebeta.prices_daily
                 WHERE instrument_id = $1
                 ORDER BY ts DESC
                 LIMIT 2
                """,
                inst["instrument_id"],
            )
        if len(rows) < 2 or not rows[0]["prev"]:
            typer.echo("Insufficient data")
            return
        ret = (float(rows[0]["close"]) / float(rows[0]["prev"]) - 1.0) * 100
        typer.echo(f"{symbol} {rows[0]['d']}: {ret:.2f}%")


@app.command("leaderboard")
def returns_leaderboard(
    window: int = typer.Option(20, "--window", help="Trading days"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Top performers by window return."""

    async def _run() -> None:
        async with async_connect() as conn:
            rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT instrument_id, ts::date AS d, close,
                           ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY ts DESC) AS rn
                      FROM theeyebeta.prices_daily
                ),
                ends AS (SELECT instrument_id, close AS end_px FROM ranked WHERE rn = 1),
                starts AS (SELECT instrument_id, close AS start_px FROM ranked WHERE rn = $1)
                SELECT i.symbol,
                       (e.end_px / s.start_px - 1) * 100 AS ret_pct
                  FROM ends e
                  JOIN starts s ON s.instrument_id = e.instrument_id
                  JOIN theeyebeta.instruments i ON i.id = e.instrument_id
                 WHERE i.active AND s.start_px > 0
                 ORDER BY ret_pct DESC
                 LIMIT $2
                """,
                window + 1,
                limit,
            )
        for row in rows:
            typer.echo(f"{row['symbol']:<8} {float(row['ret_pct']):.2f}%")

    asyncio.run(_run())
