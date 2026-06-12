#!/usr/bin/env python3
"""Expand instruments + public_ticker_map from curated plan (maintenance window only).

Dry-run by default. Never auto-sync full public.tickers map (blowout guard).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROD_ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_FILE = PROD_ROOT / "db" / "reference" / "universe_v1.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Universe expansion (dry-run default)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--top-n", type=int, default=4000)
    args = parser.parse_args()
    mode = "apply" if args.apply else "dry-run"
    print(f"expand_universe: mode={mode} top_n={args.top_n}")
    print("See docs/runbook_universe_expansion.md — execution requires operator in window")
    if args.apply:
        print("STOP: wire Massive grouped-daily selection + idempotent inserts in window")
        sys.exit(1)


if __name__ == "__main__":
    main()
