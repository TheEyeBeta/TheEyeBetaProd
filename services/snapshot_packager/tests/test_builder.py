"""Sanity tests for snapshot_packager built output.

Test 1 — Pydantic validation:
    Every built snapshot JSON round-trips through the Snapshot model without
    a ValidationError.

Test 2 — SMA20 round-trip (smoke, requires live DB):
    For AAPL in the XNAS snapshot, manually compute SMA20 from
    theeyebeta.prices_daily and assert it matches the snapshot value to 4
    decimal places (tolerates floating-point summation differences between
    polars and Python).

Test 3 — RSI bounds:
    For every symbol in every built snapshot, 0 ≤ rsi14 ≤ 100 (or None if
    the window was shorter than 14 bars).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from zinc_schemas.snapshot import Snapshot

load_dotenv(dotenv_path=str(Path(__file__).parents[3] / ".env"))

TRADE_DATE = "2026-05-21"
MARKETS = ["XNAS", "XNYS", "XSHG", "XSHE", "XTAI", "XTKS", "XHKG"]
SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "./snapshots"))


def _load(market: str) -> Snapshot:
    """Load and parse a built snapshot from disk."""
    p = SNAPSHOT_DIR / market / f"{TRADE_DATE}.json"
    if not p.exists():
        pytest.skip(f"snapshot artifact not present: {p}")
    return Snapshot.model_validate(json.loads(p.read_text()))


# ── Test 1 ───────────────────────────────────────────────────────────────────


def test_snapshots_validate_pydantic() -> None:
    """All 7 market snapshots validate against the Snapshot Pydantic model."""
    for market in MARKETS:
        snap = _load(market)
        assert snap.schema_version == 1, f"{market}: unexpected schema_version"
        assert snap.market == market, f"{market}: market field mismatch"
        assert snap.trade_date == TRADE_DATE, f"{market}: trade_date mismatch"
        assert len(snap.universe) > 0, f"{market}: empty universe"
        assert len(snap.prices) == len(snap.universe), f"{market}: prices/universe size mismatch"
        assert len(snap.technicals) == len(snap.universe), (
            f"{market}: technicals/universe size mismatch"
        )


# ── Test 2 ───────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_aapl_sma20_matches_db() -> None:
    """XNAS/AAPL SMA20 in snapshot matches SMA20 recomputed from prices_daily."""
    snap = _load("XNAS")
    symbol = "AAPL"
    entry = next((u for u in snap.universe if u.symbol == symbol), None)
    assert entry is not None, "AAPL not found in XNAS universe"

    dsn = re.sub(r"\+\w+", "", os.environ["DATABASE_URL"], count=1)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            """
            SELECT adj_close
              FROM theeyebeta.prices_daily
             WHERE instrument_id = %s
               AND ts::date <= %s
             ORDER BY ts DESC
             LIMIT 20
            """,
            (entry.instrument_id, TRADE_DATE),
        ).fetchall()

    vals = [float(r[0]) for r in rows if r[0] is not None]
    assert len(vals) == 20, f"Expected 20 adj_close rows, got {len(vals)}"

    expected = sum(vals) / len(vals)
    actual = snap.technicals[symbol].sma20
    assert actual is not None, "AAPL sma20 is None in snapshot"
    assert abs(actual - expected) < 1e-4, (
        f"SMA20 mismatch: snapshot={actual:.8f}, recomputed={expected:.8f}"
    )


# ── Test 3 ───────────────────────────────────────────────────────────────────


def test_rsi14_bounds_all_markets() -> None:
    """Every non-None RSI14 value across all market snapshots is in [0, 100]."""
    for market in MARKETS:
        snap = _load(market)
        for sym, tech in snap.technicals.items():
            if tech.rsi14 is not None:
                assert 0 <= tech.rsi14 <= 100, (
                    f"RSI14 out of bounds for {market}/{sym}: {tech.rsi14}"
                )
