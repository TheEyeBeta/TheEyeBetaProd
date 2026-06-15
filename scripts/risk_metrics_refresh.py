#!/usr/bin/env python3
"""Trigger risk_service portfolio metric recompute (for systemd timer / cron).

Reads DEFAULT_PORTFOLIO_ID or RISK_METRICS_PORTFOLIO_IDS from the environment
and POSTs to the risk-service HTTP bridge.

Usage:
    uv run python scripts/risk_metrics_refresh.py
    uv run python scripts/risk_metrics_refresh.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv()

log = structlog.get_logger()


def _portfolio_ids() -> list[str]:
    raw = os.environ.get("RISK_METRICS_PORTFOLIO_IDS", "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    default = os.environ.get("DEFAULT_PORTFOLIO_ID", "").strip()
    if default:
        return [default]
    return []


def main() -> None:
    """POST compute-portfolio-metrics for each configured portfolio."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = os.environ.get("RISK_SERVICE_URL", "http://127.0.0.1:8007").rstrip("/")
    portfolio_ids = _portfolio_ids()
    if not portfolio_ids:
        log.error("Set DEFAULT_PORTFOLIO_ID or RISK_METRICS_PORTFOLIO_IDS")
        sys.exit(1)

    for portfolio_id in portfolio_ids:
        url = f"{base}/v1/compute-portfolio-metrics"
        if args.dry_run:
            log.info("dry_run", url=url, portfolio_id=portfolio_id)
            continue
        response = httpx.post(url, json={"portfolio_id": portfolio_id}, timeout=60.0)
        response.raise_for_status()
        log.info("risk_metrics_refreshed", portfolio_id=portfolio_id, body=response.json())


if __name__ == "__main__":
    main()
