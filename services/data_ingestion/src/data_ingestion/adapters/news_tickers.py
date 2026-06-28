"""Extract ticker symbols mentioned in news text."""

from __future__ import annotations

import re


def extract_tickers(text: str, universe: set[str]) -> tuple[str, ...]:
    """Return sorted tickers found as standalone tokens in text."""
    if not text or not universe:
        return ()
    tokens = set(re.findall(r"\b[A-Z]{1,5}\b", text.upper()))
    # Drop common false positives
    stop = {
        "A",
        "AN",
        "AND",
        "ARE",
        "AS",
        "AT",
        "BE",
        "BY",
        "CEO",
        "CFO",
        "DO",
        "EU",
        "ETF",
        "FED",
        "FOR",
        "GDP",
        "HAS",
        "HE",
        "HER",
        "HIS",
        "IN",
        "IPO",
        "IS",
        "IT",
        "ITS",
        "NO",
        "OF",
        "ON",
        "OR",
        "SEC",
        "SHE",
        "SO",
        "THE",
        "TO",
        "TWO",
        "UK",
        "US",
        "USD",
        "WAS",
        "WHO",
        "WITH",
    }
    matched = sorted(t for t in tokens if t in universe and t not in stop)
    return tuple(matched)
