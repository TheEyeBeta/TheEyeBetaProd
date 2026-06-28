"""``tb now`` — live data queries (tb now commands)."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.panel import Panel
from rich.table import Table

from tb.lib.console import console
from tb.lib.db import async_connect
from tb.lib.queries.instruments import (
    fetch_latest_indicators,
    fetch_latest_price,
    resolve_symbol,
)
from tb.lib.queries.platform import fetch_platform_summary

app = typer.Typer(no_args_is_help=True, help="Query live engine state and data")

_SHORT_INDICATOR_KEYS = (
    "sma_50",
    "sma_200",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
)

_LONG_INDICATOR_KEYS = (
    "sma_10",
    "sma_50",
    "sma_200",
    "ema_10",
    "ema_50",
    "ema_200",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "roc_10",
    "roc_20",
    "golden_cross_sma",
    "death_cross_sma",
    "momentum_rank_12_1",
)


def _fmt_val(val: object) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    try:
        return f"{float(val):,.4f}"
    except (TypeError, ValueError):
        return str(val)


@app.command("status")
def now_status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Engine health and worker status."""

    async def _run() -> dict[str, object]:
        async with async_connect() as conn:
            return await fetch_platform_summary(conn)

    summary = asyncio.run(_run())
    if json_output:
        typer.echo(json.dumps(summary, indent=2, default=str))
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
                "symbol": ticker.upper(),
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
    typer.echo(f"{ticker.upper()} {p['d']} close={p['close']} vol={p['volume']}")


@app.command("indicators")
def now_indicators(
    ticker: str = typer.Argument(...),
    long: bool = typer.Option(False, "--long", "-l", help="Show full indicator set"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Latest technical indicators for a symbol."""

    async def _run() -> dict[str, object] | None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, ticker)
            if not inst:
                return None
            iid = int(inst["instrument_id"])
            row = await conn.fetchrow(
                """
                SELECT date, sma_10, sma_50, sma_200, ema_10, ema_50, ema_200,
                       ema_12, ema_26, rsi_14, macd, macd_signal, macd_hist,
                       roc_10, roc_20, golden_cross_sma, death_cross_sma,
                       momentum_rank_12_1
                  FROM theeyebeta.ind_technical_daily
                 WHERE instrument_id = $1
                 ORDER BY date DESC LIMIT 1
                """,
                iid,
            )
            price = await fetch_latest_price(conn, iid)
            return {
                "symbol": ticker.upper(),
                "indicators": dict(row) if row else None,
                "price": price,
            }

    result = asyncio.run(_run())
    if not result or not result.get("indicators"):
        typer.echo(f"No indicators for {ticker}", err=True)
        raise typer.Exit(code=1)

    ind = result["indicators"]
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
        return

    view = "Full" if long else "Summary"
    table = Table(title=f"Indicators for {ticker.upper()} ({view})")
    table.add_column("Indicator", style="cyan")
    table.add_column("Value", style="white")

    price = result.get("price")
    if price:
        table.add_row("Price", f"${float(price['close']):,.2f}")
        table.add_row("Date", str(ind["date"]))
        table.add_row("", "")

    keys = _LONG_INDICATOR_KEYS if long else _SHORT_INDICATOR_KEYS
    for key in keys:
        if key in ind:
            table.add_row(key.replace("_", " ").upper(), _fmt_val(ind[key]))

    console.print(table)


@app.command("news")
def now_news(
    ticker: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of articles"),
) -> None:
    """Recent news for a symbol."""

    async def _run() -> list[dict[str, object]]:
        async with async_connect() as conn:
            sym = ticker.upper()
            rows = await conn.fetch(
                """
                SELECT published_at, headline, source, url
                  FROM theeyebeta.news_articles
                 WHERE tickers @> ARRAY[$1::text]
                    OR $1 = ANY (tickers)
                 ORDER BY published_at DESC
                 LIMIT $2
                """,
                sym,
                limit,
            )
            if rows:
                return [dict(r) for r in rows]
            rows = await conn.fetch(
                """
                SELECT published_at, headline, source, url
                  FROM theeyebeta.market_news
                 WHERE headline ILIKE '%' || $1 || '%'
                    OR COALESCE(summary, '') ILIKE '%' || $1 || '%'
                 ORDER BY published_at DESC
                 LIMIT $2
                """,
                sym,
                limit,
            )
            return [dict(r) for r in rows]

    rows = asyncio.run(_run())
    if not rows:
        typer.echo(f"No news for {ticker.upper()}")
        return
    for row in rows:
        typer.echo(f"{row['published_at']} [{row['source']}] {row['headline']}")


@app.command("signals")
def now_signals(
    ticker: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of signals"),
) -> None:
    """Latest trading signals for a symbol."""

    async def _run() -> None:
        sym = ticker.upper()
        async with async_connect() as conn:
            rows = await conn.fetch(
                """
                SELECT s.ts, s.strategy_name, s.signal, s.confidence,
                       s.entry_price, s.target_price, s.stop_loss
                  FROM theeyebeta.signals s
                  JOIN theeyebeta.public_ticker_map m ON m.public_ticker_id = s.ticker_id
                  JOIN theeyebeta.instruments i ON i.id = m.instrument_id
                 WHERE UPPER(i.symbol) = $1
                 ORDER BY s.ts DESC
                 LIMIT $2
                """,
                sym,
                limit,
            )
        if not rows:
            typer.echo(
                f"No signals for {sym} (engine may not be writing theeyebeta.signals yet)"
            )
            return
        console.print(Panel.fit(f"Trading Signals for {sym}", style="cyan"))
        table = Table()
        table.add_column("Time")
        table.add_column("Strategy")
        table.add_column("Signal")
        table.add_column("Confidence", justify="right")
        for row in rows:
            conf = row["confidence"]
            conf_str = f"{float(conf) * 100:.1f}%" if conf is not None else "N/A"
            table.add_row(
                str(row["ts"]),
                str(row["strategy_name"]),
                str(row["signal"]),
                conf_str,
            )
        console.print(table)

    asyncio.run(_run())


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
        typer.echo(f"Diagnose {ticker.upper()} (instrument_id={iid})")
        typer.echo(f"  active: {inst['active']}")
        typer.echo(f"  daily bars: {bar_count}")
        typer.echo(f"  latest price: {price['d'] if price else 'NONE'}")
        typer.echo(f"  latest indicators: {ind['date'] if ind else 'NONE'}")
        if not ind and bar_count and int(bar_count) < 200:
            typer.echo("  likely cause: insufficient history for SMA-200")

    asyncio.run(_run())
