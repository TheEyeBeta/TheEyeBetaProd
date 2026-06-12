#!/usr/bin/env python3
"""B0 probe: Massive Stocks API endpoints for 15-min delayed intraday bars.

Prints status, truncated payloads, rate-limit headers, and a call-budget
estimate for ~499 symbols per 15-min cycle. Run before designing intraday ingest.

Usage:
    uv run python scripts/probe_massive_intraday.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

MASSIVE_BASE = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
API_KEY = os.environ.get("MASSIVE_API_KEY", "")
ACTIVE_UNIVERSE = 499
CYCLE_MINUTES = 15


def _headers(resp: httpx.Response) -> dict[str, str]:
    keys = (
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "retry-after",
    )
    return {k: resp.headers.get(k, "—") for k in keys}


def _probe(
    client: httpx.Client,
    label: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    url = f"{MASSIVE_BASE}{path}"
    resp = client.get(url, params=params or {})
    body: object
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    if isinstance(body, (dict, list)):
        text = json.dumps(body)[:800]
    else:
        text = str(body)[:800]
    return {
        "label": label,
        "status": resp.status_code,
        "rate_limits": _headers(resp),
        "payload_preview": text,
    }


def main() -> None:
    """Run Massive API probes and print decision inputs."""
    if not API_KEY:
        print("STOP: MASSIVE_API_KEY is not set in environment")
        sys.exit(2)

    yday = (date.today() - timedelta(days=1)).isoformat()
    results: list[dict[str, object]] = []

    with httpx.Client(
        timeout=30.0,
        headers={"Authorization": f"Bearer {API_KEY}"},
    ) as client:
        results.append(
            _probe(
                client,
                "(a) per-ticker 15m range AAPL",
                f"/v2/aggs/ticker/AAPL/range/15/minute/{yday}/{yday}",
                params={"adjusted": "true", "sort": "asc", "limit": 5},
            ),
        )
        results.append(
            _probe(
                client,
                "(b) grouped daily reference",
                f"/v2/aggs/grouped/locale/us/market/stocks/{yday}",
                params={"adjusted": "true"},
            ),
        )
        results.append(
            _probe(
                client,
                "(c) snapshot tickers",
                "/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": "AAPL,MSFT"},
            ),
        )

    for item in results:
        print(f"\n=== {item['label']} ===")
        print(f"HTTP {item['status']}")
        print("rate_limits:", item["rate_limits"])
        print("payload:", item["payload_preview"])

    per_ticker_calls = ACTIVE_UNIVERSE
    grouped_calls = 0
    a_ok = results[0]["status"] == 200
    b_ok = results[1]["status"] == 200

    print("\n=== DECISION INPUTS ===")
    print(f"universe_size: {ACTIVE_UNIVERSE}")
    print(f"per_15m_cycle_per_ticker_calls: {per_ticker_calls if a_ok else 'N/A (endpoint failed)'}")
    print(f"per_15m_cycle_grouped_calls: {grouped_calls} (grouped is daily, not intraday)")

    if not a_ok:
        print("\nSTOP: 15-min per-ticker endpoint not available on this plan — operator decides on upgrade")
        sys.exit(1)

    limit_hdr = results[0]["rate_limits"].get("x-ratelimit-limit", "—")
    print(f"plan_rate_limit_header: {limit_hdr}")
    print(
        "recommendation: token-bucket per ticker if limit < universe; "
        "else batch parallel with cap",
    )


if __name__ == "__main__":
    main()
