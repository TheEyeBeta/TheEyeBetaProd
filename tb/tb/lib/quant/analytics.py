"""Quant analytics (ported from TheEyeBetaLocal core, theeyebeta schema)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import optimize, stats


@dataclass
class PortfolioResult:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "expected_return": self.expected_return,
            "volatility": self.volatility,
            "sharpe_ratio": self.sharpe_ratio,
        }


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.astype(float).pct_change().dropna(how="all")


def _annualize(mean: float, vol: float, rf: float = 0.0) -> tuple[float, float, float]:
    ann_ret = mean * 252
    ann_vol = vol * np.sqrt(252)
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0.0
    return ann_ret, ann_vol, sharpe


def optimize_sharpe(
    prices: pd.DataFrame,
    *,
    risk_free_rate: float = 0.0,
    allow_short: bool = False,
) -> PortfolioResult:
    rets = _returns(prices).dropna(axis=1, how="any")
    tickers = list(rets.columns)
    mu = rets.mean().values
    cov = rets.cov().values
    n = len(tickers)

    def neg_sharpe(w: np.ndarray) -> float:
        port_ret = w @ mu
        port_vol = np.sqrt(w @ cov @ w)
        if port_vol <= 0:
            return 1e6
        return -((port_ret * 252 - risk_free_rate) / (port_vol * np.sqrt(252)))

    bounds = [(-1, 1) if allow_short else (0, 1)] * n
    cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    x0 = np.full(n, 1 / n)
    res = optimize.minimize(
        neg_sharpe, x0, bounds=bounds, constraints=cons, method="SLSQP"
    )
    w = res.x
    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(w @ cov @ w))
    ann_ret, ann_vol, sharpe = _annualize(port_ret, port_vol, risk_free_rate)
    return PortfolioResult(
        weights={t: float(wi) for t, wi in zip(tickers, w, strict=True)},
        expected_return=ann_ret,
        volatility=ann_vol,
        sharpe_ratio=sharpe,
    )


def optimize_risk_parity(prices: pd.DataFrame) -> PortfolioResult:
    rets = _returns(prices).dropna(axis=1, how="any")
    tickers = list(rets.columns)
    cov = rets.cov().values
    n = len(tickers)

    def risk_budget_obj(w: np.ndarray) -> float:
        port_vol = np.sqrt(w @ cov @ w)
        if port_vol <= 0:
            return 1e6
        marginal = cov @ w
        risk_contrib = w * marginal / port_vol
        target = port_vol / n
        return float(np.sum((risk_contrib - target) ** 2))

    cons = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
    bounds = [(0, 1)] * n
    x0 = np.full(n, 1 / n)
    res = optimize.minimize(
        risk_budget_obj, x0, bounds=bounds, constraints=cons, method="SLSQP"
    )
    w = res.x
    mu = rets.mean().values
    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(w @ cov @ w))
    ann_ret, ann_vol, sharpe = _annualize(port_ret, port_vol)
    return PortfolioResult(
        weights={t: float(wi) for t, wi in zip(tickers, w, strict=True)},
        expected_return=ann_ret,
        volatility=ann_vol,
        sharpe_ratio=sharpe,
    )


def max_sharpe_frontier(
    prices: pd.DataFrame, *, risk_free_rate: float = 0.0
) -> PortfolioResult:
    return optimize_sharpe(prices, risk_free_rate=risk_free_rate, allow_short=False)


def historical_var(
    returns: pd.Series,
    *,
    confidence: float = 0.95,
) -> dict[str, float]:
    r = returns.dropna().astype(float)
    if r.empty:
        return {}
    var = float(np.quantile(r, 1 - confidence))
    tail = r[r <= var]
    cvar = float(tail.mean()) if len(tail) else var
    return {
        f"var_{int(confidence * 100)}": var,
        f"cvar_{int(confidence * 100)}": cvar,
        "mean_return": float(r.mean()),
        "volatility": float(r.std()),
    }


def capm_beta(
    asset: pd.Series, market: pd.Series, *, risk_free_rate: float = 0.0
) -> dict[str, float]:
    df = pd.concat([asset, market], axis=1, keys=["asset", "market"]).dropna()
    rets = df.pct_change().dropna()
    if len(rets) < 30:
        return {}
    y = rets["asset"].values - risk_free_rate / 252
    x = rets["market"].values - risk_free_rate / 252
    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    alpha_daily = intercept
    return {
        "beta_market": float(slope),
        "alpha": float(alpha_daily),
        "alpha_annualized": float(alpha_daily * 252),
        "r_squared": float(r_value**2),
        "n_observations": len(rets),
    }


def rolling_correlation(
    returns: pd.DataFrame, window: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tail = returns.tail(window)
    return tail.corr(), tail.cov() * 252


def find_cointegrated_pairs(
    prices: pd.DataFrame, *, max_pairs: int = 10
) -> list[dict[str, Any]]:
    from statsmodels.tsa.stattools import coint

    cols = list(prices.columns)
    results: list[dict[str, Any]] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            pair = prices[[a, b]].dropna()
            if len(pair) < 60:
                continue
            score, pvalue, _ = coint(pair[a], pair[b])
            if pvalue >= 0.05:
                continue
            hedge = float(np.polyfit(pair[b], pair[a], 1)[0])
            spread = pair[a] - hedge * pair[b]
            half_life = None
            lag = spread.shift(1).dropna()
            delta = spread.diff().dropna()
            aligned = pd.concat([lag, delta], axis=1).dropna()
            if len(aligned) > 10:
                beta = np.polyfit(aligned.iloc[:, 0], aligned.iloc[:, 1], 1)[0]
                if beta < 0:
                    half_life = float(-np.log(2) / beta)
            results.append(
                {
                    "ticker_x": a,
                    "ticker_y": b,
                    "p_value": float(pvalue),
                    "hedge_ratio": hedge,
                    "half_life": half_life,
                }
            )
    results.sort(key=lambda r: r["p_value"])
    return results[:max_pairs]


def mc_european_option(
    *,
    spot: float,
    strike: float,
    maturity: float,
    sigma: float,
    rate: float,
    option_type: str,
    n_paths: int = 10_000,
    n_steps: int = 1,
) -> float:
    rng = np.random.default_rng(42)
    if n_steps <= 1:
        z = rng.standard_normal(n_paths)
        st = spot * np.exp(
            (rate - 0.5 * sigma**2) * maturity + sigma * np.sqrt(maturity) * z
        )
    else:
        dt = maturity / n_steps
        st = np.full(n_paths, spot)
        for _ in range(n_steps):
            z = rng.standard_normal(n_paths)
            st *= np.exp((rate - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z)
    if option_type.lower().startswith("p"):
        payoffs = np.maximum(strike - st, 0)
    else:
        payoffs = np.maximum(st - strike, 0)
    return float(np.exp(-rate * maturity) * payoffs.mean())


def black_scholes(
    *,
    spot: float,
    strike: float,
    maturity: float,
    sigma: float,
    rate: float,
    option_type: str,
) -> float:
    if maturity <= 0 or sigma <= 0:
        return (
            max(0.0, spot - strike)
            if option_type.lower().startswith("c")
            else max(0.0, strike - spot)
        )
    d1 = (np.log(spot / strike) + (rate + 0.5 * sigma**2) * maturity) / (
        sigma * np.sqrt(maturity)
    )
    d2 = d1 - sigma * np.sqrt(maturity)
    if option_type.lower().startswith("p"):
        return float(
            strike * np.exp(-rate * maturity) * stats.norm.cdf(-d2)
            - spot * stats.norm.cdf(-d1)
        )
    return float(
        spot * stats.norm.cdf(d1)
        - strike * np.exp(-rate * maturity) * stats.norm.cdf(d2)
    )
