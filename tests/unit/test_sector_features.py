"""Unit tests for the ARGOS sector_context builder."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from workers.sector_features import build_sector_context_from_rows


def test_missing_rows_reports_gap_never_fabricates() -> None:
    assert build_sector_context_from_rows([], date(2026, 6, 10)) == {
        "data_gaps": ["sector_context"],
    }
    assert build_sector_context_from_rows([{"sector": "Tech"}], None) == {
        "data_gaps": ["sector_context"],
    }


def test_block_shape_rotation_sorted_and_breadth() -> None:
    rows = [
        {
            "sector": "Utilities",
            "rotation_rank": 2,
            "rel_strength_spx_30d": Decimal("0.010000"),
            "pct_above_sma_50": Decimal("40.000"),
            "pct_above_sma_200": Decimal("35.500"),
        },
        {
            "sector": "Technology",
            "rotation_rank": 1,
            "rel_strength_spx_30d": Decimal("0.041000"),
            "pct_above_sma_50": Decimal("61.200"),
            "pct_above_sma_200": Decimal("48.700"),
        },
        {
            "sector": "UNKNOWN",
            "rotation_rank": None,
            "rel_strength_spx_30d": None,
            "pct_above_sma_50": None,
            "pct_above_sma_200": None,
        },
    ]
    block = build_sector_context_from_rows(rows, date(2026, 6, 11))

    assert block["as_of_date"] == "2026-06-11"
    assert block["data_gaps"] == []
    assert [r["sector"] for r in block["rotation"]] == [
        "Technology",
        "Utilities",
        "UNKNOWN",
    ]
    assert block["rotation"][0] == {
        "sector": "Technology",
        "rank": 1,
        "rel_strength_spx_30d": 0.041,
    }
    assert block["breadth"]["Technology"] == {
        "pct_above_sma_50": 61.2,
        "pct_above_sma_200": 48.7,
    }
    assert block["breadth"]["UNKNOWN"] == {
        "pct_above_sma_50": None,
        "pct_above_sma_200": None,
    }
