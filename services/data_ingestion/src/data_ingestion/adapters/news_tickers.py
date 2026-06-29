"""Extract ticker symbols mentioned in news text."""

from __future__ import annotations

import re


def extract_tickers(text: str, universe: set[str]) -> tuple[str, ...]:
    """Return sorted uppercase ticker-like tokens found in text."""
    if not text or not universe:
        return ()
    tokens = {
        match.group(1) for match in re.finditer(r"(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])", text)
    }
    tokens.update(
        match.group(1).upper()
        for match in re.finditer(r"(?<![A-Za-z])\$([A-Za-z]{1,5})(?![A-Za-z])", text)
    )
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
        "TIME",
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
