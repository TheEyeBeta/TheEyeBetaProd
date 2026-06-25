"""``tb quant`` — quantitative analytics (Local CLI parity)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from tb.lib.quant.analytics import (
    black_scholes,
    capm_beta,
    find_cointegrated_pairs,
    historical_var,
    max_sharpe_frontier,
    mc_european_option,
    optimize_risk_parity,
    optimize_sharpe,
    rolling_correlation,
)
from tb.lib.quant.data import load_indicator_frame, load_price_frame

app = typer.Typer(no_args_is_help=True, help="Quantitative analytics")
console = Console()

_BENCHMARK_ALIASES = {
    "^GSPC": "SPY",
    "GSPC": "SPY",
    "^SPX": "SPY",
    "SPX": "SPY",
    "^NDX": "QQQ",
    "NDX": "QQQ",
}


def _parse_tickers(value: str) -> list[str]:
    return [t.strip().upper() for t in value.split(",") if t.strip()]


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"Invalid {name}: use YYYY-MM-DD") from exc


@app.command("returns")
def quant_returns(
    tickers: str = typer.Argument(..., help="Comma-separated symbols"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
) -> None:
    """Daily returns and volatility summary."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start"),
            end=_parse_date(end, "end"),
        )

    prices = asyncio.run(_run())
    if prices.empty:
        raise typer.Exit(code=1)
    returns = prices.pct_change().dropna()
    vol = returns.rolling(20).std() * (252**0.5)
    cum = (1 + returns).cumprod() - 1

    table = Table(title="Returns & Volatility")
    table.add_column("Ticker")
    table.add_column("Total Return", justify="right")
    table.add_column("Ann. Vol (20d)", justify="right")
    for sym in prices.columns:
        table.add_row(
            sym,
            f"{float(cum[sym].iloc[-1]) * 100:6.2f}%",
            f"{float(vol[sym].iloc[-1]) * 100:6.2f}%",
        )
    console.print(table)


@app.command("corr")
def quant_corr(
    tickers: str = typer.Argument(...),
    window: int = typer.Option(60, "--window"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Rolling correlation and covariance."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
            limit=max(window + 5, 120),
        )

    prices = asyncio.run(_run())
    if prices.empty or len(prices) < window:
        typer.echo("Insufficient data", err=True)
        raise typer.Exit(code=1)
    returns = prices.pct_change().dropna()
    mat, cov = rolling_correlation(returns, window)
    console.print("[bold]Correlation matrix[/bold]")
    console.print(mat)
    console.print("\n[bold]Covariance (annualized)[/bold]")
    console.print(cov)


@app.command("sharpe-opt")
def quant_sharpe_opt(
    tickers: str = typer.Argument(...),
    rf: float = typer.Option(0.0, "--rf"),
    allow_short: bool = typer.Option(False, "--allow-short"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Maximize portfolio Sharpe ratio."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
        )

    prices = asyncio.run(_run())
    if prices.empty:
        raise typer.Exit(code=1)
    result = optimize_sharpe(prices, risk_free_rate=rf, allow_short=allow_short)
    console.print(result.to_dict())


@app.command("var")
def quant_var(
    tickers: str = typer.Argument(...),
    confidence: float = typer.Option(0.95, "--confidence"),
    window: int = typer.Option(252, "--window"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Historical VaR / CVaR for equal-weight portfolio."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
            limit=window + 1,
        )

    prices = asyncio.run(_run())
    if prices.empty:
        raise typer.Exit(code=1)
    weights = 1.0 / len(prices.columns)
    port = (prices * weights).sum(axis=1)
    rets = port.pct_change().dropna().tail(window)
    metrics = historical_var(rets, confidence=confidence)
    for key, val in metrics.items():
        if key.startswith(("var_", "cvar_")):
            typer.echo(f"{key}: {val * 100:.2f}%")
        else:
            typer.echo(f"{key}: {val:.6f}")


@app.command("risk-parity")
def quant_risk_parity(
    tickers: str = typer.Argument(...),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Risk parity portfolio weights."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
        )

    prices = asyncio.run(_run())
    if prices.empty:
        raise typer.Exit(code=1)
    console.print(optimize_risk_parity(prices).to_dict())


@app.command("capm")
def quant_capm(
    ticker: str = typer.Argument(...),
    market: str = typer.Argument(..., help="Benchmark e.g. SPY"),
    rf: float = typer.Option(0.0, "--rf"),
) -> None:
    """CAPM beta and alpha."""

    asset = ticker.upper()
    bench = _BENCHMARK_ALIASES.get(market.upper(), market.upper())

    async def _run() -> tuple[pd.Series, pd.Series]:
        px = await load_price_frame([asset, bench])
        return px[asset], px[bench]

    asset_px, market_px = asyncio.run(_run())
    if asset_px.empty or market_px.empty:
        typer.echo("Missing price data", err=True)
        raise typer.Exit(code=1)
    metrics = capm_beta(asset_px, market_px, risk_free_rate=rf)
    console.print(metrics)


@app.command("frontier")
def quant_frontier(
    tickers: str = typer.Argument(...),
    rf: float = typer.Option(0.0, "--rf"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Efficient frontier tangency (max Sharpe) portfolio."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
        )

    prices = asyncio.run(_run())
    if prices.empty:
        raise typer.Exit(code=1)
    console.print(max_sharpe_frontier(prices, risk_free_rate=rf).to_dict())


@app.command("pairs")
def quant_pairs(
    tickers: str = typer.Argument(...),
    max_pairs: int = typer.Option(10, "--max-pairs"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
) -> None:
    """Cointegrated pairs scan."""

    async def _run() -> pd.DataFrame:
        return await load_price_frame(
            _parse_tickers(tickers),
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
        )

    prices = asyncio.run(_run())
    if prices.shape[1] < 2:
        typer.echo("Need at least two symbols with data", err=True)
        raise typer.Exit(code=1)
    results = find_cointegrated_pairs(prices, max_pairs=max_pairs)
    if not results:
        typer.echo("No cointegrated pairs found")
        return
    table = Table(title="Cointegrated pairs")
    table.add_column("Pair")
    table.add_column("p-value", justify="right")
    table.add_column("Hedge", justify="right")
    table.add_column("Half-life", justify="right")
    for row in results:
        table.add_row(
            f"{row['ticker_x']}-{row['ticker_y']}",
            f"{row['p_value']:.4f}",
            f"{row['hedge_ratio']:.4f}",
            f"{row['half_life']:.1f}" if row.get("half_life") else "N/A",
        )
    console.print(table)


@app.command("mc-option")
def quant_mc_option(
    spot: float = typer.Argument(...),
    strike: float = typer.Argument(...),
    maturity: float = typer.Argument(...),
    sigma: float = typer.Argument(...),
    r: float = typer.Option(0.02, "--r"),
    n_paths: int = typer.Option(10_000, "--paths"),
    n_steps: int = typer.Option(252, "--steps"),
    call_put: str = typer.Option("call", "--type"),
) -> None:
    """Monte Carlo European option price."""
    mc = mc_european_option(
        spot=spot,
        strike=strike,
        maturity=maturity,
        sigma=sigma,
        rate=r,
        option_type=call_put,
        n_paths=n_paths,
        n_steps=n_steps,
    )
    bs = black_scholes(
        spot=spot,
        strike=strike,
        maturity=maturity,
        sigma=sigma,
        rate=r,
        option_type=call_put,
    )
    typer.echo(f"MC price: ${mc:.4f}")
    typer.echo(f"Black-Scholes: ${bs:.4f}")


@app.command("ema-backtest")
def quant_ema_backtest(
    ticker: str = typer.Argument(...),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    fast_period: int = typer.Option(50, "--fast"),
    slow_period: int = typer.Option(200, "--slow"),
    initial_cash: float = typer.Option(10_000.0, "--cash"),
) -> None:
    """EMA crossover backtest using theeyebeta indicators."""

    async def _run() -> pd.DataFrame:
        return await load_indicator_frame(
            ticker,
            start=_parse_date(start, "start") if start else None,
            end=_parse_date(end, "end") if end else None,
        )

    df = asyncio.run(_run())
    if df.empty:
        raise typer.Exit(code=1)

    fast_col = "ema_12" if fast_period <= 12 else "sma_50" if fast_period <= 50 else "sma_200"
    slow_col = "sma_200" if slow_period >= 200 else "ema_26"
    if fast_col not in df.columns or slow_col not in df.columns:
        typer.echo("Missing indicator columns for requested periods", err=True)
        raise typer.Exit(code=1)

    cash = initial_cash
    shares = 0.0
    trades = 0
    prev_above: bool | None = None
    for _, row in df.iterrows():
        fast = row[fast_col]
        slow = row[slow_col]
        if pd.isna(fast) or pd.isna(slow):
            continue
        above = float(fast) > float(slow)
        price = float(row["close"])
        if prev_above is not None:
            if above and not prev_above and shares == 0:
                shares = cash / price
                cash = 0.0
                trades += 1
            elif not above and prev_above and shares > 0:
                cash = shares * price
                shares = 0.0
                trades += 1
        prev_above = above

    final = cash + shares * float(df.iloc[-1]["close"])
    total_return = (final - initial_cash) / initial_cash
    typer.echo(f"{ticker.upper()} EMA backtest")
    typer.echo(f"  final equity: ${final:,.2f}")
    typer.echo(f"  total return: {total_return * 100:+.2f}%")
    typer.echo(f"  trades: {trades}")
