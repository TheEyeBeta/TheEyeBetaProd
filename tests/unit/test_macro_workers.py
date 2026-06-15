from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from workers.macro_calculations import (
    annualized_qoq_pct,
    classify_rate_environment,
    compute_month_over_month_diff,
    compute_style_tilts,
    compute_yoy_percent,
)
from workers.macro_features import build_macro_feature_block_from_row


def test_payrolls_month_over_month_diff() -> None:
    points = [
        (date(2026, 1, 1), 158_000.0),
        (date(2026, 2, 1), 158_125.0),
        (date(2026, 3, 1), 158_095.0),
    ]

    assert compute_month_over_month_diff(points) == [
        (date(2026, 2, 1), 125.0),
        (date(2026, 3, 1), -30.0),
    ]


def test_pce_core_yoy_against_published_fred_print() -> None:
    points = [
        (date(2024, 4, 1), 122.304),
        (date(2024, 5, 1), 122.383),
        (date(2024, 6, 1), 122.677),
        (date(2024, 7, 1), 122.911),
        (date(2024, 8, 1), 123.128),
        (date(2024, 9, 1), 123.466),
        (date(2024, 10, 1), 123.832),
        (date(2024, 11, 1), 123.962),
        (date(2024, 12, 1), 124.196),
        (date(2025, 1, 1), 124.587),
        (date(2025, 2, 1), 125.145),
        (date(2025, 3, 1), 125.267),
        (date(2025, 4, 1), 125.502),
    ]

    assert compute_yoy_percent(points)[-1] == (
        date(2025, 4, 1),
        pytest.approx(2.6148, abs=0.05),
    )


def test_gdp_qoq_pct_is_annualized() -> None:
    assert annualized_qoq_pct(23770.976, 23548.210) == pytest.approx(3.8380, abs=0.0001)


def test_cpi_yoy_uses_twelve_month_observation_offset() -> None:
    latest_cpi = 332.407
    year_ago_cpi = 324.122
    yoy = (latest_cpi / year_ago_cpi - 1.0) * 100.0
    assert yoy == pytest.approx(2.5567, abs=0.05)


def test_rate_environment_threshold_boundaries() -> None:
    assert classify_rate_environment(None) == "unknown"
    assert classify_rate_environment(0.0500) == "neutral"
    assert classify_rate_environment(-0.0500) == "neutral"
    assert classify_rate_environment(0.0501) == "hiking"
    assert classify_rate_environment(-0.0501) == "cutting"


def test_style_tilts_are_clamped() -> None:
    tilts = compute_style_tilts(
        "hiking",
        "inverted",
        "stressed",
        "crisis",
        "strong",
    )

    for key in [
        "momentum_weight",
        "valuation_weight",
        "quality_weight",
        "risk_weight",
        "growth_weight",
    ]:
        assert 0.70 <= tilts[key] <= 1.40


def test_macro_feature_nulls_propagate_to_data_gaps() -> None:
    row = {
        "as_of_date": date(2026, 6, 10),
        "fed_funds_rate": Decimal("4.3300"),
        "yield_2y": Decimal("4.0000"),
        "yield_10y": Decimal("4.5600"),
        "spread_2s10s": Decimal("0.5600"),
        "fed_funds_change_30d": None,
        "yield_10y_change_30d": Decimal("0.1000"),
        "yield_2y_change_30d": None,
        "spread_2s10s_change_30d": None,
        "cpi": Decimal("320.5800"),
        "cpi_yoy_pct": None,
        "cpi_surprise": None,
        "gdp": Decimal("23770.9760"),
        "gdp_qoq_pct": None,
        "vix": Decimal("17.2500"),
        "vix_change_5d": None,
        "vix_pct_rank_1y": None,
        "hy_oas_bps": Decimal("310.0000"),
        "hy_oas_change_30d": None,
        "sp500_level": Decimal("6000.0000"),
        "sp500_change_5d_pct": None,
        "sp500_change_30d_pct": None,
        "nasdaq_level": Decimal("19000.0000"),
        "nasdaq_change_5d_pct": None,
        "nasdaq_change_30d_pct": None,
        "dxy": Decimal("99.5000"),
        "dxy_change_5d": None,
        "dxy_change_30d": None,
        "rate_environment": "neutral",
        "yield_curve": "normal",
        "credit_environment": "tight",
        "volatility_regime": "elevated",
        "dollar_regime": "unknown",
        "style_tilts": {"momentum_weight": 1.0},
    }

    block = build_macro_feature_block_from_row(row)

    assert block["fed_funds_change_30d"] is None
    assert block["cpi_yoy_pct"] is None
    assert "fed_funds_change_30d" in block["data_gaps"]
    assert "cpi_yoy_pct" in block["data_gaps"]
    assert "cpi_surprise" not in block["data_gaps"]
    assert block["yield_10y_change_30d"] == 0.1
    assert "yield_10y_change_30d" not in block["data_gaps"]
