#!/usr/bin/env python3
"""Dry-run report for trimming theeyebeta.public_ticker_map blowout rows.

Identifies map rows to KEEP (referenced by active instruments or theeyebeta FK
usage) vs DELETE CANDIDATES. Never deletes without explicit ``--apply`` and
operator review of the dry-run report.

Requires SELECT on theeyebeta.public_ticker_map (run as postgres/tb_app on server).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
import psycopg
from dotenv import load_dotenv

load_dotenv()

_raw_url = os.environ.get("DATABASE_URL", "")
DATABASE_URL: str = re.sub(r"\+\w+", "", _raw_url, count=1)

# Tables with instrument_id FK usage in theeyebeta (schema-qualified).
FK_INSTRUMENT_TABLES: tuple[str, ...] = (
    "theeyebeta.prices_daily",
    "theeyebeta.prices_intraday",
    "theeyebeta.ind_technical_daily",
    "theeyebeta.ind_risk_daily",
    "theeyebeta.returns_snapshot_daily",
    "theeyebeta.sector_daily",
    "theeyebeta.signals",
    "theeyebeta.orders",
    "theeyebeta.positions",
    "theeyebeta.fundamentals_company",
    "theeyebeta.corporate_actions",
    "theeyebeta.agent_decisions",
)


@dataclass(frozen=True, slots=True)
class MapRow:
    """One public_ticker_map row."""

    public_ticker_id: int
    instrument_id: int
    symbol: str
    synced_at: object


@dataclass(frozen=True, slots=True)
class TrimReport:
    """Summary of keep vs delete candidates."""

    total_map_rows: int
    keep_rows: int
    delete_candidates: int
    blowout_day_counts: list[tuple[object, int]]
    keep_reasons: dict[str, int]
    sample_deletes: list[MapRow]


def _p(msg: str = "") -> None:
    print(msg, flush=True)


def _table_exists(conn: psycopg.Connection, qualified: str) -> bool:
    schema, table = qualified.split(".", 1)
    row = conn.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = %s
           AND table_name = %s
        """,
        (schema, table),
    ).fetchone()
    return row is not None


def _collect_keep_instrument_ids(conn: psycopg.Connection) -> tuple[set[int], dict[str, int]]:
    """Build the instrument_id keep-set and per-reason counts."""
    reasons: dict[str, int] = {}
    keep: set[int] = set()

    active_rows = conn.execute(
        """
        SELECT id
          FROM theeyebeta.instruments
         WHERE active
        """,
    ).fetchall()
    for (iid,) in active_rows:
        keep.add(int(iid))
    reasons["active_instruments"] = len(active_rows)

    mapped_active = conn.execute(
        """
        SELECT DISTINCT m.instrument_id
          FROM theeyebeta.public_ticker_map m
          JOIN theeyebeta.instruments i ON i.id = m.instrument_id
         WHERE i.active
        """,
    ).fetchall()
    reasons["active_mapped"] = len(mapped_active)

    for qualified in FK_INSTRUMENT_TABLES:
        if not _table_exists(conn, qualified):
            continue
        try:
            rows = conn.execute(
                f"SELECT DISTINCT instrument_id FROM {qualified} WHERE instrument_id IS NOT NULL",  # noqa: S608
            ).fetchall()
        except psycopg.Error:
            conn.rollback()
            continue
        label = qualified.split(".", 1)[1]
        added = 0
        for (iid,) in rows:
            if int(iid) not in keep:
                keep.add(int(iid))
                added += 1
        if added:
            reasons[f"fk:{label}"] = added

    return keep, reasons


def _load_map_rows(conn: psycopg.Connection) -> list[MapRow]:
    cols = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'theeyebeta'
           AND table_name = 'public_ticker_map'
        """,
    ).fetchall()
    col_names = {str(r[0]) for r in cols}
    synced_expr = "synced_at" if "synced_at" in col_names else "NULL::timestamptz"
    rows = conn.execute(
        f"""
        SELECT public_ticker_id, instrument_id, symbol, {synced_expr} AS synced_at
          FROM theeyebeta.public_ticker_map
         ORDER BY instrument_id, public_ticker_id
        """,  # noqa: S608
    ).fetchall()
    return [
        MapRow(
            public_ticker_id=int(r[0]),
            instrument_id=int(r[1]),
            symbol=str(r[2]),
            synced_at=r[3],
        )
        for r in rows
    ]


def _blowout_histogram(conn: psycopg.Connection) -> list[tuple[object, int]]:
    """Rows per synced_at day (or instrument created_at proxy if map lacks synced_at)."""
    cols = conn.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'theeyebeta'
           AND table_name = 'public_ticker_map'
        """,
    ).fetchall()
    col_names = {str(r[0]) for r in cols}
    if "synced_at" in col_names:
        rows = conn.execute(
            """
            SELECT date_trunc('day', synced_at)::date AS d, COUNT(*)
              FROM theeyebeta.public_ticker_map
             GROUP BY 1
             ORDER BY 1 DESC NULLS LAST
             LIMIT 15
            """,
        ).fetchall()
        return [(r[0], int(r[1])) for r in rows]

    rows = conn.execute(
        """
        SELECT date_trunc('day', i.created_at)::date AS d, COUNT(*)
          FROM theeyebeta.public_ticker_map m
          JOIN theeyebeta.instruments i ON i.id = m.instrument_id
         GROUP BY 1
         ORDER BY 1 DESC
         LIMIT 15
        """,
    ).fetchall()
    return [(r[0], int(r[1])) for r in rows]


def build_report(conn: psycopg.Connection) -> TrimReport:
    """Compute keep vs delete-candidate counts."""
    keep_ids, keep_reasons = _collect_keep_instrument_ids(conn)
    map_rows = _load_map_rows(conn)
    blowout = _blowout_histogram(conn)

    keep_rows = [r for r in map_rows if r.instrument_id in keep_ids]
    delete_candidates = [r for r in map_rows if r.instrument_id not in keep_ids]

    return TrimReport(
        total_map_rows=len(map_rows),
        keep_rows=len(keep_rows),
        delete_candidates=len(delete_candidates),
        blowout_day_counts=blowout,
        keep_reasons=keep_reasons,
        sample_deletes=delete_candidates[:25],
    )


def apply_deletes(conn: psycopg.Connection, instrument_ids: list[int]) -> int:
    """Delete map rows for non-kept instrument_ids (operator-approved only)."""
    if not instrument_ids:
        return 0
    with conn.transaction():
        result = conn.execute(
            """
            DELETE FROM theeyebeta.public_ticker_map
             WHERE instrument_id = ANY(%s::bigint[])
            """,
            (instrument_ids,),
        )
    return result.rowcount or 0


def print_report(report: TrimReport, *, dry_run: bool) -> None:
    """Print operator-facing trim report."""
    _p("=== public_ticker_map trim report ===")
    _p(f"mode: {'dry-run' if dry_run else 'APPLY (destructive)'}")
    _p(f"total_map_rows: {report.total_map_rows}")
    _p(f"keep_rows: {report.keep_rows}")
    _p(f"delete_candidates: {report.delete_candidates}")
    _p("\n-- blowout histogram (synced_at day or instrument created_at) --")
    for day, count in report.blowout_day_counts:
        _p(f"  {day}: {count}")
    _p("\n-- keep reasons (instrument_id sources) --")
    for reason, count in sorted(report.keep_reasons.items()):
        _p(f"  {reason}: {count}")
    if report.sample_deletes:
        _p("\n-- sample delete candidates (first 25) --")
        for row in report.sample_deletes:
            _p(
                f"  ticker_id={row.public_ticker_id} "
                f"instrument_id={row.instrument_id} "
                f"symbol={row.symbol} synced_at={row.synced_at}",
            )
    if report.delete_candidates and dry_run:
        _p(
            "\nGATE: Review delete_candidates count above. "
            "Re-run with --apply ONLY after operator approval."
        )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Report (and optionally trim) public_ticker_map blowout rows",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="DELETE candidate rows (requires operator approval of dry-run first)",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    if not DATABASE_URL:
        _p("ERROR: DATABASE_URL is not set")
        sys.exit(1)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            report = build_report(conn)
            print_report(report, dry_run=dry_run)

            if not dry_run and report.delete_candidates:
                keep_ids, _ = _collect_keep_instrument_ids(conn)
                map_rows = _load_map_rows(conn)
                all_delete_ids = sorted(
                    {r.instrument_id for r in map_rows if r.instrument_id not in keep_ids},
                )
                deleted = apply_deletes(conn, all_delete_ids)
                _p(f"\nDELETED map rows: {deleted} (instrument_ids={len(all_delete_ids)})")
    except psycopg.errors.InsufficientPrivilege as exc:
        _p("ERROR: insufficient privilege on public_ticker_map")
        _p(f"  detail: {exc}")
        _p("\n-- fallback: instruments blowout proxy (readable with tb_app) --")
        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(
                """
                SELECT date_trunc('day', created_at)::date AS d,
                       COUNT(*) FILTER (WHERE active) AS active_n,
                       COUNT(*) FILTER (WHERE NOT active) AS inactive_n
                  FROM theeyebeta.instruments
                 GROUP BY 1
                 ORDER BY 1 DESC
                 LIMIT 10
                """,
            ).fetchall()
            total_inst = conn.execute("SELECT COUNT(*) FROM theeyebeta.instruments").fetchone()[0]
            active_inst = conn.execute(
                "SELECT COUNT(*) FROM theeyebeta.instruments WHERE active",
            ).fetchone()[0]
            _p(f"  instruments_total: {total_inst} active: {active_inst}")
            for d, active_n, inactive_n in rows:
                _p(f"  created {d}: active={active_n} inactive={inactive_n}")
            _p(
                "\n  Map trim dry-run requires postgres on server. "
                "Re-run: sudo -u postgres psql ... -f or DATABASE_URL as postgres."
            )
        sys.exit(2)


if __name__ == "__main__":
    main()
