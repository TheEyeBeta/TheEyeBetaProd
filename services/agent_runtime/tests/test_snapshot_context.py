"""Tests for LLM snapshot trimming."""

from __future__ import annotations

from agent_runtime.snapshot_context import snapshot_for_llm, snapshot_metadata


def _big_snapshot(symbol_count: int) -> dict:
    universe = [
        {
            "symbol": f"S{i}",
            "instrument_id": i,
            "sector": "Technology",
            "industry": None,
        }
        for i in range(symbol_count)
    ]
    prices = {
        f"S{i}": {
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "adj_close": 1.5,
            "volume": i,
        }
        for i in range(symbol_count)
    }
    technicals = {
        f"S{i}": {
            "atr14": 1.0,
            "adx14": 20.0,
            "rsi14": 50.0,
            "zscore20": 0.0,
            "bb_upper20_2": 2.0,
            "bb_lower20_2": 1.0,
        }
        for i in range(symbol_count)
    }
    return {
        "schema_version": 1,
        "market": "US",
        "snapshot_id": "test-snapshot",
        "as_of": "2026-06-16T23:59:59+00:00",
        "universe": universe,
        "prices": prices,
        "technicals": technicals,
        "macro": {"macro.us.dgs10": 4.25},
        "news_summary": [{"id": 1, "headline": "Test", "tickers": ["S1"], "published_at": None}],
    }


def test_snapshot_metadata_counts_universe() -> None:
    snap = _big_snapshot(5)
    meta = snapshot_metadata(snap)
    assert meta["universe_total"] == 5
    assert meta["market"] == "US"


def test_snapshot_for_llm_run_caps_symbols() -> None:
    snap = _big_snapshot(500)
    view = snapshot_for_llm(snap, kind="run")
    assert view["universe_total"] == 500
    assert view["universe_included"] == 150
    assert len(view["universe"]) == 150
    assert view["universe"][0]["symbol"] == "S499"


def test_snapshot_for_llm_rollup_omits_instrument_payload() -> None:
    snap = _big_snapshot(500)
    view = snapshot_for_llm(snap, kind="rollup")
    assert "prices" not in view
    assert "technicals" not in view
    assert view["universe_total"] == 500
    assert "note" in view
