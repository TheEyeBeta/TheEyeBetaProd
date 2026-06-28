"""FRED series and ETF proxy definitions for the fixed-income v1 worker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FredSeries:
    """One FRED source series used by the fixed-income regime layer."""

    series_code: str
    description: str
    category: str


@dataclass(frozen=True, slots=True)
class FixedIncomeETFProxy:
    """ETF proxy instrument used for public fixed-income price context."""

    symbol: str
    exchange_code: str
    name: str
    proxy_type: str


FRED_SERIES: dict[str, FredSeries] = {
    "DGS1MO": FredSeries("DGS1MO", "1-Month Treasury Constant Maturity", "treasury_yield"),
    "DGS3MO": FredSeries("DGS3MO", "3-Month Treasury Constant Maturity", "treasury_yield"),
    "DGS6MO": FredSeries("DGS6MO", "6-Month Treasury Constant Maturity", "treasury_yield"),
    "DGS1": FredSeries("DGS1", "1-Year Treasury Constant Maturity", "treasury_yield"),
    "DGS2": FredSeries("DGS2", "2-Year Treasury Constant Maturity", "treasury_yield"),
    "DGS5": FredSeries("DGS5", "5-Year Treasury Constant Maturity", "treasury_yield"),
    "DGS10": FredSeries("DGS10", "10-Year Treasury Constant Maturity", "treasury_yield"),
    "DGS20": FredSeries("DGS20", "20-Year Treasury Constant Maturity", "treasury_yield"),
    "DGS30": FredSeries("DGS30", "30-Year Treasury Constant Maturity", "treasury_yield"),
    "T10Y2Y": FredSeries("T10Y2Y", "10-Year Minus 2-Year Treasury Spread", "curve_spread"),
    "T10Y3M": FredSeries("T10Y3M", "10-Year Minus 3-Month Treasury Spread", "curve_spread"),
    "DFII10": FredSeries("DFII10", "10-Year Treasury Inflation-Indexed Security", "real_yield"),
    "BAMLH0A0HYM2": FredSeries(
        "BAMLH0A0HYM2",
        "ICE BofA US High Yield Option-Adjusted Spread",
        "credit_spread",
    ),
    "BAMLC0A0CM": FredSeries(
        "BAMLC0A0CM",
        "ICE BofA US Corporate Option-Adjusted Spread",
        "credit_spread",
    ),
}

ETF_PROXIES: tuple[FixedIncomeETFProxy, ...] = (
    FixedIncomeETFProxy("SHY", "ARCX", "iShares 1-3 Year Treasury Bond ETF", "short_treasury"),
    FixedIncomeETFProxy(
        "IEF",
        "ARCX",
        "iShares 7-10 Year Treasury Bond ETF",
        "intermediate_treasury",
    ),
    FixedIncomeETFProxy("TLT", "ARCX", "iShares 20+ Year Treasury Bond ETF", "long_treasury"),
    FixedIncomeETFProxy("TIP", "ARCX", "iShares TIPS Bond ETF", "inflation_linked"),
    FixedIncomeETFProxy("BND", "XNAS", "Vanguard Total Bond Market ETF", "aggregate_bond"),
    FixedIncomeETFProxy("AGG", "ARCX", "iShares Core U.S. Aggregate Bond ETF", "aggregate_bond"),
)

ETF_PROXY_SYMBOLS: tuple[str, ...] = tuple(proxy.symbol for proxy in ETF_PROXIES)
