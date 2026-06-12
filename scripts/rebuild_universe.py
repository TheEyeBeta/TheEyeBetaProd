#!/usr/bin/env python3
"""Reconcile theeyebeta.instruments.active from a curated symbol list.

Reads ``db/reference/universe_v1.txt`` (one symbol per line) and sets
``instruments.active`` true/false accordingly. Never deletes instrument rows;
``delisted_at`` is preserved unless ``--apply`` also passes ``--clear-delisted``
for symbols being reactivated.

Default is ``--dry-run`` (report only). Pass ``--apply`` to write changes.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

PROD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE_FILE = PROD_ROOT / "db" / "reference" / "universe_v1.txt"

_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL: str = re.sub(r"\+\w+", "", _raw_url, count=1)


@dataclass(frozen=True, slots=True)
class InstrumentRow:
    """One row from theeyebeta.instruments."""

    instrument_id: int
    symbol: str
    active: bool
    delisted_at: object


@dataclass(frozen=True, slots=True)
class UniverseDiff:
    """Planned active-flag changes."""

    to_activate: list[InstrumentRow]
    to_deactivate: list[InstrumentRow]
    missing_in_db: list[str]
    inactive_in_db: list[str]


def load_universe_file(path: Path) -> list[str]:
    """Load curated symbols from a text file (comments and blanks skipped)."""
    if not path.is_file():
        msg = f"Universe file not found: {path}"
        raise FileNotFoundError(msg)
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.split("#", 1)[0].strip().upper()
        if raw:
            symbols.append(raw)
    return sorted(set(symbols))


def _index_by_symbol(db_rows: list[InstrumentRow]) -> dict[str, InstrumentRow]:
    """Map symbol -> row, preferring active over inactive when duplicates exist."""
    by_symbol: dict[str, InstrumentRow] = {}
    for row in db_rows:
        key = row.symbol.upper()
        existing = by_symbol.get(key)
        if existing is None or (row.active and not existing.active):
            by_symbol[key] = row
    return by_symbol


def compute_diff(
    curated: list[str],
    db_rows: list[InstrumentRow],
) -> UniverseDiff:
    """Compare curated list against current DB state."""
    by_symbol = _index_by_symbol(db_rows)
    curated_set = set(curated)

    to_activate: list[InstrumentRow] = []
    to_deactivate: list[InstrumentRow] = []
    missing_in_db: list[str] = []
    inactive_in_db: list[str] = []

    for symbol in curated:
        row = by_symbol.get(symbol)
        if row is None:
            missing_in_db.append(symbol)
        elif not row.active:
            inactive_in_db.append(symbol)
            to_activate.append(row)

    for row in db_rows:
        sym = row.symbol.upper()
        canonical = by_symbol.get(sym)
        if canonical is not None and row.instrument_id != canonical.instrument_id:
            continue
        if sym not in curated_set and row.active:
            to_deactivate.append(row)

    return UniverseDiff(
        to_activate=to_activate,
        to_deactivate=to_deactivate,
        missing_in_db=missing_in_db,
        inactive_in_db=inactive_in_db,
    )


def fetch_instruments(conn: psycopg.Connection) -> list[InstrumentRow]:
    """Load all instrument rows (active and inactive)."""
    rows = conn.execute(
        """
        SELECT id, symbol, active, delisted_at
          FROM theeyebeta.instruments
         ORDER BY symbol
        """,
    ).fetchall()
    return [
        InstrumentRow(
            instrument_id=int(r[0]),
            symbol=str(r[1]),
            active=bool(r[2]),
            delisted_at=r[3],
        )
        for r in rows
    ]


def apply_diff(
    conn: psycopg.Connection,
    diff: UniverseDiff,
    *,
    clear_delisted: bool,
) -> dict[str, int]:
    """Apply active-flag updates inside a transaction."""
    activated = 0
    deactivated = 0
    with conn.transaction():
        for row in diff.to_activate:
            if clear_delisted:
                conn.execute(
                    """
                    UPDATE theeyebeta.instruments
                       SET active = true,
                           delisted_at = NULL,
                           updated_at = now()
                     WHERE id = %s
                    """,
                    (row.instrument_id,),
                )
            else:
                conn.execute(
                    """
                    UPDATE theeyebeta.instruments
                       SET active = true,
                           updated_at = now()
                     WHERE id = %s
                    """,
                    (row.instrument_id,),
                )
            activated += 1
        for row in diff.to_deactivate:
            conn.execute(
                """
                UPDATE theeyebeta.instruments
                   SET active = false,
                       updated_at = now()
                 WHERE id = %s
                """,
                (row.instrument_id,),
            )
            deactivated += 1
    return {"activated": activated, "deactivated": deactivated}


def print_report(
    curated: list[str],
    db_rows: list[InstrumentRow],
    diff: UniverseDiff,
    *,
    dry_run: bool,
) -> None:
    """Emit a human-readable diff report."""
    active_db = sum(1 for r in db_rows if r.active)
    print(f"curated_symbols: {len(curated)}")
    print(f"db_instruments: {len(db_rows)} (active={active_db})")
    print(f"to_activate: {len(diff.to_activate)}")
    print(f"to_deactivate: {len(diff.to_deactivate)}")
    print(f"missing_in_db: {len(diff.missing_in_db)}")
    print(f"mode: {'dry-run' if dry_run else 'apply'}")

    if diff.to_activate:
        print("\n-- would activate --")
        for row in diff.to_activate[:20]:
            print(f"  {row.symbol} (id={row.instrument_id})")
        if len(diff.to_activate) > 20:
            print(f"  ... and {len(diff.to_activate) - 20} more")

    if diff.to_deactivate:
        print("\n-- would deactivate --")
        for row in diff.to_deactivate[:20]:
            print(f"  {row.symbol} (id={row.instrument_id})")
        if len(diff.to_deactivate) > 20:
            print(f"  ... and {len(diff.to_deactivate) - 20} more")

    if diff.missing_in_db:
        print("\n-- curated but missing in DB (no insert; operator must add manually) --")
        for sym in diff.missing_in_db[:20]:
            print(f"  {sym}")
        if len(diff.missing_in_db) > 20:
            print(f"  ... and {len(diff.missing_in_db) - 20} more")


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Reconcile instruments.active from db/reference/universe_v1.txt",
    )
    parser.add_argument(
        "--universe-file",
        type=Path,
        default=DEFAULT_UNIVERSE_FILE,
        help="Curated symbol list (default: db/reference/universe_v1.txt)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write active-flag changes (default: dry-run report only)",
    )
    parser.add_argument(
        "--clear-delisted",
        action="store_true",
        help="When activating, also NULL delisted_at (off by default)",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    curated = load_universe_file(args.universe_file)
    with psycopg.connect(DATABASE_URL) as conn:
        db_rows = fetch_instruments(conn)
        diff = compute_diff(curated, db_rows)
        print_report(curated, db_rows, diff, dry_run=dry_run)

        if not dry_run and (diff.to_activate or diff.to_deactivate):
            counts = apply_diff(conn, diff, clear_delisted=args.clear_delisted)
            print(f"\napplied: {counts}")
        elif not dry_run:
            print("\nno changes to apply")


if __name__ == "__main__":
    main()
