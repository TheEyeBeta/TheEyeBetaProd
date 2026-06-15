"""``tb quant`` — quantitative analytics."""

from __future__ import annotations

import asyncio

import typer

from tb.lib.db import async_connect
from tb.lib.queries.instruments import fetch_price_series, resolve_symbol

app = typer.Typer(no_args_is_help=True, help="Quantitative analytics")


@app.command("returns")
def quant_returns(
    symbol: str = typer.Argument(...), window: int = typer.Option(20, "--window")
) -> None:
    """Daily returns and volatility."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            rows = await fetch_price_series(
                conn, int(inst["instrument_id"]), limit=window + 1
            )
        if len(rows) < 2:
            typer.echo("Insufficient data")
            return
        rets = []
        for i in range(1, len(rows)):
            rets.append(float(rows[i]["close"]) / float(rows[i - 1]["close"]) - 1.0)
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        typer.echo(f"{symbol} mean={mean:.4f} vol={var**0.5:.4f} ({len(rets)} days)")

    asyncio.run(_run())


@app.command("corr")
def quant_corr(
    symbol_a: str = typer.Argument(...),
    symbol_b: str = typer.Argument(...),
    window: int = typer.Option(60, "--window"),
) -> None:
    """Rolling correlation between two symbols."""

    async def _run() -> None:
        async with async_connect() as conn:
            ia = await resolve_symbol(conn, symbol_a)
            ib = await resolve_symbol(conn, symbol_b)
            if not ia or not ib:
                raise typer.Exit(code=1)
            pa = await fetch_price_series(conn, int(ia["instrument_id"]), limit=window)
            pb = await fetch_price_series(conn, int(ib["instrument_id"]), limit=window)
        n = min(len(pa), len(pb))
        if n < 5:
            typer.echo("Insufficient overlap")
            return
        ra = [
            float(pa[i]["close"]) / float(pa[i - 1]["close"]) - 1 for i in range(1, n)
        ]
        rb = [
            float(pb[i]["close"]) / float(pb[i - 1]["close"]) - 1 for i in range(1, n)
        ]
        ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
        cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(len(ra))) / len(ra)
        sa = (sum((x - ma) ** 2 for x in ra) / len(ra)) ** 0.5
        sb = (sum((x - mb) ** 2 for x in rb) / len(rb)) ** 0.5
        corr = cov / (sa * sb) if sa and sb else 0.0
        typer.echo(f"corr({symbol_a},{symbol_b}) = {corr:.4f}")

    asyncio.run(_run())


@app.command("var")
def quant_var(
    symbol: str = typer.Argument(...), alpha: float = typer.Option(0.05, "--alpha")
) -> None:
    """Historical VaR from daily returns."""

    async def _run() -> None:
        async with async_connect() as conn:
            inst = await resolve_symbol(conn, symbol)
            if not inst:
                raise typer.Exit(code=1)
            rows = await fetch_price_series(conn, int(inst["instrument_id"]), limit=252)
        rets = sorted(
            float(rows[i]["close"]) / float(rows[i - 1]["close"]) - 1
            for i in range(1, len(rows))
        )
        idx = max(0, int(len(rets) * alpha) - 1)
        typer.echo(f"{symbol} VaR({alpha:.0%}) = {rets[idx]:.4f}")

    asyncio.run(_run())
