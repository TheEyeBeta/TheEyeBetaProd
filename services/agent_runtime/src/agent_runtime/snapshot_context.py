"""Trim packaged snapshots for LLM prompts (full universe can exceed token limits)."""

from __future__ import annotations

import os
from typing import Any

_DEFAULT_MAX_SYMBOLS = 150


def _max_symbols() -> int:
    raw = os.environ.get("AGENT_SNAPSHOT_MAX_SYMBOLS", str(_DEFAULT_MAX_SYMBOLS))
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_SYMBOLS


def snapshot_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return snapshot header fields without per-instrument payloads."""
    return {
        "schema_version": snapshot.get("schema_version"),
        "market": snapshot.get("market"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "as_of": snapshot.get("as_of"),
        "universe_total": len(snapshot.get("universe") or []),
    }


def _top_symbols_by_volume(
    snapshot: dict[str, Any],
    *,
    limit: int,
) -> list[str]:
    prices = snapshot.get("prices") or {}
    ranked = sorted(
        prices.items(),
        key=lambda item: int(item[1].get("volume") or 0),
        reverse=True,
    )
    return [symbol for symbol, _ in ranked[:limit]]


def snapshot_for_llm(
    snapshot: dict[str, Any],
    *,
    kind: str,
) -> dict[str, Any]:
    """Build a token-bounded snapshot view for the LLM user message.

    Rollup runs synthesize subordinate briefings and only need snapshot metadata.
    Standard runs include macro, news, and the most liquid symbols by volume.
    """
    meta = snapshot_metadata(snapshot)
    if kind == "rollup":
        return {
            **meta,
            "macro": snapshot.get("macro") or {},
            "news_summary": (snapshot.get("news_summary") or [])[:20],
            "note": (
                "Full packaged snapshot is stored at snapshot_id; "
                "synthesize from subordinate_reports."
            ),
        }

    limit = _max_symbols()
    symbols = _top_symbols_by_volume(snapshot, limit=limit)
    universe_by_symbol = {
        row["symbol"]: row for row in (snapshot.get("universe") or []) if "symbol" in row
    }
    prices = snapshot.get("prices") or {}
    technicals = snapshot.get("technicals") or {}

    return {
        **meta,
        "universe_included": len(symbols),
        "universe": [universe_by_symbol[s] for s in symbols if s in universe_by_symbol],
        "prices": {s: prices[s] for s in symbols if s in prices},
        "technicals": {s: technicals[s] for s in symbols if s in technicals},
        "macro": snapshot.get("macro") or {},
        "news_summary": snapshot.get("news_summary") or [],
    }
