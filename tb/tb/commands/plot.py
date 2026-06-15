"""``tb plot`` — chart data summaries (terminal output)."""

from __future__ import annotations

import asyncio

import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import fetch_latest_indicators, fetch_price_series, resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Price and indicator charts")


def _plot_symbol(symbol: str, *, mode: str, limit: int = 30) -> None:
    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            prices = await fetch_price_series(conn, int(inst["instrument_id"]), limit=limit)
            ind = await fetch_latest_indicators(conn, int(inst["instrument_id"]))
        typer.echo(f"=== {symbol} {mode} (last {len(prices)} bars) ===")
        for row in prices[-10:]:
            line = f"{row['d']} close={row['close']}"
            if mode in {"ema", "all"} and ind:
                line += f" sma50={ind.get('sma_50')}"
            if mode == "volume":
                line = f"{row['d']} vol={row['volume']}"
            typer.echo(line)

    asyncio.run(_run())


@app.command("price")
def plot_price(symbol: str = typer.Argument(...), limit: int = typer.Option(30, "--limit")) -> None:
    """Price series summary."""
    _plot_symbol(symbol, mode="price", limit=limit)


@app.command("ema")
def plot_ema(symbol: str = typer.Argument(...)) -> None:
    """Price with EMA context."""
    _plot_symbol(symbol, mode="ema")


@app.command("sma")
def plot_sma(symbol: str = typer.Argument(...)) -> None:
    """Price with SMA context."""
    _plot_symbol(symbol, mode="sma")


@app.command("volume")
def plot_volume(symbol: str = typer.Argument(...)) -> None:
    """Volume series."""
    _plot_symbol(symbol, mode="volume")


@app.command("rsi")
def plot_rsi(symbol: str = typer.Argument(...)) -> None:
    """RSI from latest indicators."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            ind = await fetch_latest_indicators(conn, int(inst["instrument_id"]))
        rsi = ind.get("rsi_14") if ind else "N/A"
        dt = ind["date"] if ind else "N/A"
        typer.echo(f"{symbol} RSI-14 @ {dt}: {rsi}")

    asyncio.run(_run())


@app.command("all")
def plot_all(symbol: str = typer.Argument(...)) -> None:
    """Combined price/indicator summary."""
    _plot_symbol(symbol, mode="all")
