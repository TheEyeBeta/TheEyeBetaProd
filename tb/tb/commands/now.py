"""``tb now`` — live data queries."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.panel import Panel

from tb.lib.console import console
from tb.lib.db import async_connect
from tb.lib.queries.instruments import (
    fetch_latest_indicators,
    fetch_latest_price,
    resolve_symbol,
)
from tb.lib.queries.platform import fetch_platform_summary

app = typer.Typer(no_args_is_help=True, help="Query live engine state and data")


@app.command("status")
def now_status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Engine health and worker status."""

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_platform_summary(conn)

    summary = asyncio.run(_run())
    if json_output:
        typer.echo(json.dumps(summary, indent=2))
        return
    console.print(Panel.fit("Engine NOW status", style="bold cyan"))
    for key, value in summary.items():
        if key != "stale_heartbeats":
            typer.echo(f"  {key}: {value}")


@app.command("price")
def now_price(
    ticker: str = typer.Argument(..., help="Symbol e.g. AAPL"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Latest daily price for a symbol."""

    async def _run() -> dict[str, object] | None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, ticker)
            if not inst:
                return None
            price = await fetch_latest_price(conn, int(inst["instrument_id"]))
            return {
                "symbol": ticker,
                "instrument_id": inst["instrument_id"],
                "price": price,
            }

    result = asyncio.run(_run())
    if not result or not result.get("price"):
        typer.echo(f"No price for {ticker}", err=True)
        raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return
    p = result["price"]
    typer.echo(f"{ticker} {p['d']} close={p['close']} vol={p['volume']}")


@app.command("indicators")
def now_indicators(
    ticker: str = typer.Argument(...),
    long: bool = typer.Option(False, "--long", help="Show full indicator set"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Latest technical indicators for a symbol."""

    async def _run() -> dict[str, object] | None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, ticker)
            if not inst:
                return None
            ind = await fetch_latest_indicators(conn, int(inst["instrument_id"]))
            return {"symbol": ticker, "indicators": ind}

    result = asyncio.run(_run())
    if not result or not result.get("indicators"):
        typer.echo(f"No indicators for {ticker}", err=True)
        raise typer.Exit(code=1)
    ind = result["indicators"]
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return
    typer.echo(f"{ticker} indicators @ {ind['date']}")
    keys = list(ind.keys()) if long else ["sma_50", "sma_200", "rsi_14", "macd"]
    for key in keys:
        if key in ind and ind[key] is not None:
            typer.echo(f"  {key}: {ind[key]}")


@app.command("news")
def now_news(
    ticker: str = typer.Argument(...),
    limit: int = typer.Option(5, "--limit"),
) -> None:
    """Recent news for a symbol (if news tables populated)."""

    async def _run() -> None:
        async with async_connect() as conn:
            exists = await conn.fetchval(
                """
                SELECT 1 FROM information_schema.tables
                 WHERE table_schema='theeyebeta' AND table_name='news_articles'
                """,
            )
            if not exists:
                typer.echo("news_articles table not present", err=True)
                raise typer.Exit(code=1)
            rows = await conn.fetch(
                """
                SELECT published_at, headline, source
                  FROM theeyebeta.news_articles
                 WHERE symbol = $1
                 ORDER BY published_at DESC
                 LIMIT $2
                """,
                ticker.upper(),
                limit,
            )
        for row in rows:
            typer.echo(f"{row['published_at']} [{row['source']}] {row['headline']}")

    asyncio.run(_run())


@app.command("signals")
def now_signals(
    ticker: str = typer.Argument(...), limit: int = typer.Option(5, "--limit")
) -> None:
    """Latest trading signals (if signals table populated)."""
    typer.echo(
        f"Signals query for {ticker} — check agent-runtime when deployed (limit={limit})"
    )


@app.command("diagnose")
def now_diagnose(ticker: str = typer.Argument(...)) -> None:
    """Diagnose why indicators may be missing for a symbol."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, ticker)
            if not inst:
                typer.echo(f"Symbol {ticker} not in instruments")
                return
            iid = int(inst["instrument_id"])
            price = await fetch_latest_price(conn, iid)
            ind = await fetch_latest_indicators(conn, iid)
            bar_count = await conn.fetchval(
                "SELECT COUNT(*) FROM theeyebeta.prices_daily WHERE instrument_id=$1",
                iid,
            )
        typer.echo(f"Diagnose {ticker} (instrument_id={iid})")
        typer.echo(f"  active: {inst['active']}")
        typer.echo(f"  daily bars: {bar_count}")
        typer.echo(f"  latest price: {price['d'] if price else 'NONE'}")
        typer.echo(f"  latest indicators: {ind['date'] if ind else 'NONE'}")
        if not ind and bar_count and int(bar_count) < 200:
            typer.echo("  likely cause: insufficient history for SMA-200")

    asyncio.run(_run())
