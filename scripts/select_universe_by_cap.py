#!/usr/bin/env python3
"""Select EOD or intraday universe tiers from market-cap snapshots.

Tiers:
  - ``eod``: all mapped symbols with positive market cap (~11k) → nightly EOD prices
  - ``intraday``: symbols >= $500M (~4.6k) → 15-minute bars during market hours

Writes ``db/reference/universe_eod.txt`` or ``universe_v2.txt`` and optionally
reconciles ``theeyebeta.instruments.active`` for the EOD tier only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import date
from pathlib import Path

import asyncpg
import structlog

PROD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTRADAY_OUTPUT = PROD_ROOT / "db" / "reference" / "universe_v2.txt"
DEFAULT_EOD_OUTPUT = PROD_ROOT / "db" / "reference" / "universe_eod.txt"

sys.path.insert(0, str(PROD_ROOT))

from workers.market_cap_providers import CAP_THRESHOLD_USD  # noqa: E402

log = structlog.get_logger()

_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL: str = re.sub(r"\+\w+", "", _raw_url, count=1)


async def resolve_latest_cap_date(conn: asyncpg.Connection, as_of: date) -> date:
    """Return the latest cap snapshot date on or before ``as_of``."""
    value = await conn.fetchval(
        """
        SELECT MAX(as_of_date)
          FROM theeyebeta.market_cap_daily
         WHERE as_of_date <= $1
        """,
        as_of,
    )
    if value is None:
        msg = "No rows in theeyebeta.market_cap_daily; run fetch_market_cap first"
        raise RuntimeError(msg)
    return value


async def select_symbols_by_cap(
    conn: asyncpg.Connection,
    *,
    as_of_date: date,
    min_cap: float,
    max_cap: float | None = None,
    require_mapped: bool = True,
) -> list[str]:
    """Return sorted symbols meeting cap bounds with DB eligibility filters."""
    map_join = (
        "JOIN theeyebeta.public_ticker_map m ON m.instrument_id = i.id" if require_mapped else ""
    )
    cap_upper = "AND c.market_cap <= $3" if max_cap is not None else ""
    params: list[object] = [as_of_date, min_cap]
    if max_cap is not None:
        params.append(max_cap)
    rows = await conn.fetch(
        f"""
        SELECT DISTINCT i.symbol
          FROM theeyebeta.market_cap_daily c
          JOIN theeyebeta.instruments i ON i.symbol = c.symbol
          {map_join}
         WHERE c.as_of_date = $1
           AND c.market_cap >= $2
           {cap_upper}
           AND (i.delisted_at IS NULL OR i.delisted_at > $1)
         ORDER BY i.symbol
        """,
        *params,
    )
    return [str(row["symbol"]).upper() for row in rows]


def write_universe_file(path: Path, symbols: list[str]) -> None:
    """Write one symbol per line to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{symbol}\n" for symbol in symbols), encoding="utf-8")


async def async_main(args: argparse.Namespace) -> None:
    """Load caps, write universe file, and optionally apply active flags."""
    if not DATABASE_URL:
        msg = "DATABASE_URL is not set"
        raise RuntimeError(msg)

    as_of = date.fromisoformat(args.date) if args.date else date.today()
    tier = args.tier
    if tier == "eod":
        min_cap = float(args.min_cap)
        max_cap = None
        default_output = DEFAULT_EOD_OUTPUT
    else:
        min_cap = float(args.threshold)
        max_cap = None
        default_output = DEFAULT_INTRADAY_OUTPUT

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        cap_date = await resolve_latest_cap_date(conn, as_of)
        symbols = await select_symbols_by_cap(
            conn,
            as_of_date=cap_date,
            min_cap=min_cap,
            max_cap=max_cap,
            require_mapped=not args.include_unmapped,
        )
    finally:
        await conn.close()

    output = args.output or default_output
    write_universe_file(output, symbols)

    log.info(
        "universe_selected",
        cap_date=cap_date.isoformat(),
        tier=tier,
        min_cap=min_cap,
        count=len(symbols),
        output=str(output),
    )
    print(f"tier: {tier}")
    print(f"cap_date: {cap_date.isoformat()}")
    print(f"min_cap_usd: {min_cap:,.0f}")
    print(f"selected_symbols: {len(symbols)}")
    print(f"output: {output}")
    if symbols:
        print(f"sample: {', '.join(symbols[:10])}")

    if args.apply:
        if tier != "eod":
            msg = "--apply only applies to the EOD tier (sets instruments.active)"
            raise RuntimeError(msg)
        import psycopg

        from scripts.rebuild_universe import (  # noqa: PLC0415
            apply_diff,
            compute_diff,
            fetch_instruments,
            load_universe_file,
        )

        curated = load_universe_file(output)
        with psycopg.connect(DATABASE_URL) as sync_conn:
            db_rows = fetch_instruments(sync_conn)
            diff = compute_diff(curated, db_rows)
            if diff.to_activate or diff.to_deactivate:
                counts = apply_diff(sync_conn, diff, clear_delisted=args.clear_delisted)
                print(f"applied: {counts}")
            else:
                print("no instrument active-flag changes required")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Select universe tier from market-cap snapshots",
    )
    parser.add_argument(
        "--tier",
        choices=["eod", "intraday"],
        default="intraday",
        help="eod = all positive caps; intraday = >= threshold (default: intraday)",
    )
    parser.add_argument("--date", help="As-of date YYYY-MM-DD; default today")
    parser.add_argument(
        "--threshold",
        type=float,
        default=CAP_THRESHOLD_USD,
        help="Intraday minimum market cap in USD (default: 500000000)",
    )
    parser.add_argument(
        "--min-cap",
        type=float,
        default=1.0,
        help="EOD minimum market cap in USD (default: 1 — any positive cap)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output universe file path (tier-specific default if omitted)",
    )
    parser.add_argument(
        "--include-unmapped",
        action="store_true",
        help="Include instruments without public_ticker_map rows",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Reconcile instruments.active from the generated EOD tier file",
    )
    parser.add_argument(
        "--clear-delisted",
        action="store_true",
        help="When activating, also NULL delisted_at (off by default)",
    )
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
