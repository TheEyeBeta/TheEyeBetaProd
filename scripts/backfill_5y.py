#!/usr/bin/env python3
"""Per-chunk 5-year prices_daily backfill with checkpoint table (maintenance window).

Honors theeyebeta.backfill_progress; decompress → insert → recompress per chunk.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="5y backfill engine")
    parser.add_argument("--chunk", help="Specific chunk name")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dry = not args.apply
    print(f"backfill_5y: dry_run={dry} chunk={args.chunk} resume={args.resume}")
    print("See docs/runbook_universe_expansion.md")
    if args.apply:
        print("STOP: run only in maintenance window with operator present")
        sys.exit(1)


if __name__ == "__main__":
    main()
