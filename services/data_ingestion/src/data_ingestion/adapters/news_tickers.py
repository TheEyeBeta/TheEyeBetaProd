"""Extract ticker symbols mentioned in news text."""

from __future__ import annotations

import re


def extract_tickers(text: str, universe: set[str]) -> tuple[str, ...]:
    """Return sorted tickers found as standalone tokens in text."""
    if not text or not universe:
        return ()
    tokens = set(re.findall(r"\b[A-Z]{1,5}\b", text.upper()))
    # Drop common false positives
    stop = {"USD", "CEO", "CFO", "IPO", "ETF", "GDP", "FED", "SEC", "AI", "US", "UK", "EU"}
    matched = sorted(t for t in tokens if t in universe and t not in stop)
    return tuple(matched)
