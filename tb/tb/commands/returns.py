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
                WITH ranked_prices AS (
                    SELECT ts::date AS d, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY ts::date
                               ORDER BY
                                   CASE source
                                       WHEN 'massive' THEN 100
                                       WHEN 'yfinance_backfill_prices' THEN 90
                                       WHEN 'yfinance_gap_fix' THEN 90
                                       WHEN 'yfinance' THEN 80
                                       WHEN 'finnhub' THEN 70
                                       WHEN 'public_mirror_backfill' THEN 60
                                       WHEN 'public_mirror_active_universe' THEN 50
                                       WHEN 'tick_rollup' THEN 40
                                       WHEN 'csv' THEN 10
                                       ELSE 0
                                   END DESC,
                                   ts DESC,
                                   ingested_at DESC
                           ) AS rn
                      FROM theeyebeta.prices_daily
                     WHERE instrument_id = $1
                ),
                canonical AS (
                    SELECT d, close
                      FROM ranked_prices
                     WHERE rn = 1
                ),
                with_prev AS (
                    SELECT d, close, LAG(close) OVER (ORDER BY d) AS prev
                      FROM canonical
                )
                SELECT d, close, prev
                  FROM with_prev
                 ORDER BY d DESC
                 LIMIT 1
                """,
                inst["instrument_id"],
            )
        if not rows or not rows[0]["prev"]:
            typer.echo("Insufficient data")
            return
        ret = (float(rows[0]["close"]) / float(rows[0]["prev"]) - 1.0) * 100
        typer.echo(f"{symbol} {rows[0]['d']}: {ret:.2f}%")

    asyncio.run(_run())


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
                    SELECT instrument_id, d, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY instrument_id ORDER BY d DESC
                           ) AS rn
                      FROM (
                            SELECT instrument_id, ts::date AS d, close,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY instrument_id, ts::date
                                       ORDER BY
                                           CASE source
                                               WHEN 'massive' THEN 100
                                               WHEN 'yfinance_backfill_prices' THEN 90
                                               WHEN 'yfinance_gap_fix' THEN 90
                                               WHEN 'yfinance' THEN 80
                                               WHEN 'finnhub' THEN 70
                                               WHEN 'public_mirror_backfill' THEN 60
                                               WHEN 'public_mirror_active_universe' THEN 50
                                               WHEN 'tick_rollup' THEN 40
                                               WHEN 'csv' THEN 10
                                               ELSE 0
                                           END DESC,
                                           ts DESC,
                                           ingested_at DESC
                                   ) AS daily_rn
                              FROM theeyebeta.prices_daily
                      ) daily
                     WHERE daily_rn = 1
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
