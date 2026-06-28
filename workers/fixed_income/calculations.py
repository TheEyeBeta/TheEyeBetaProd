"""Deterministic fixed-income regime calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, value))


def classify_curve_regime(
    spread_10y_2y: float | None,
    spread_10y_3m: float | None,
) -> str:
    """Classify the Treasury curve using percent-point spreads."""
    twos_tens = _to_float(spread_10y_2y)
    threes_tens = _to_float(spread_10y_3m)
    spreads = [value for value in (twos_tens, threes_tens) if value is not None]
    if not spreads:
        return "unknown"
    if len(spreads) == 2 and all(value < 0 for value in spreads):
        return "deep_inversion"
    if any(value < 0 for value in spreads):
        return "partial_inversion"
    if twos_tens is not None and twos_tens < 0.25:
        return "flat"
    if twos_tens is not None and twos_tens >= 1.00:
        return "steep"
    return "normal"


def classify_rate_regime(
    y_10y_change_20d: float | None,
    y_2y_change_20d: float | None,
) -> str:
    """Classify recent rate movement from 20-trading-day changes."""
    y10 = _to_float(y_10y_change_20d)
    y2 = _to_float(y_2y_change_20d)
    if y10 is None or y2 is None:
        return "unknown"

    slope_change = y10 - y2
    if y10 >= 0.40 and y2 >= 0.40:
        return "broad_rate_shock"
    if y10 <= -0.40 and y2 <= -0.40:
        return "broad_rate_collapse"
    if y10 >= 0.30 and slope_change >= 0.25:
        return "bear_steepening"
    if y2 <= -0.30 and slope_change >= 0.25:
        return "bull_steepening"
    return "stable"


def classify_credit_regime(high_yield_spread: float | None) -> str:
    """Classify credit stress from HY OAS in percent."""
    hy = _to_float(high_yield_spread)
    if hy is None:
        return "unknown"
    if hy >= 7.0:
        return "severe_credit_stress"
    if hy >= 5.0:
        return "elevated_credit_stress"
    if hy >= 3.5:
        return "mild_credit_stress"
    return "normal_credit"


def calculate_bond_environment_score(
    *,
    curve_regime: str,
    rate_regime: str,
    real_yield_10y: float | None,
    credit_regime: str,
) -> int:
    """Return a 0-100 fixed-income backdrop score for equity/macro context."""
    score = 50

    score += {
        "steep": 8,
        "normal": 3,
        "flat": -6,
        "partial_inversion": -12,
        "deep_inversion": -18,
    }.get(curve_regime, 0)

    score += {
        "stable": 5,
        "bull_steepening": 10,
        "broad_rate_collapse": 6,
        "bear_steepening": -8,
        "broad_rate_shock": -15,
    }.get(rate_regime, 0)

    score += {
        "normal_credit": 10,
        "mild_credit_stress": -4,
        "elevated_credit_stress": -15,
        "severe_credit_stress": -25,
    }.get(credit_regime, 0)

    real_yield = _to_float(real_yield_10y)
    if real_yield is not None:
        if real_yield >= 2.25:
            score -= 10
        elif real_yield >= 1.50:
            score -= 5
        elif real_yield < 0:
            score += 8
        elif real_yield <= 0.50:
            score += 5

    return _clamp(score)


def classify_bond_environment(score: int | None) -> str:
    """Convert the numeric score to a stable label."""
    if score is None:
        return "unknown"
    if score >= 75:
        return "equity_supportive"
    if score >= 55:
        return "mildly_supportive"
    if score >= 45:
        return "neutral"
    if score >= 30:
        return "equity_hostile"
    return "severe_risk_off"


def generate_fixed_income_signals(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate interpretable fixed-income signals from one metric row."""
    signals: list[dict[str, Any]] = []

    spread_10y_2y = _to_float(row.get("spread_10y_2y"))
    spread_10y_3m = _to_float(row.get("spread_10y_3m"))
    inversion_spreads = [
        value for value in (spread_10y_2y, spread_10y_3m) if value is not None and value < 0
    ]
    if inversion_spreads:
        value = min(inversion_spreads)
        signals.append(
            {
                "signal_name": "curve_inversion",
                "value": value,
                "strength": (
                    "strong" if value <= -1.0 or len(inversion_spreads) == 2 else "moderate"
                ),
                "direction": "risk_off",
                "interpretation": (
                    "Treasury curve inversion points to tighter forward growth conditions."
                ),
            }
        )

    y10_change = _to_float(row.get("y_10y_change_20d"))
    y2_change = _to_float(row.get("y_2y_change_20d"))
    rate_pressure = max(
        [value for value in (y10_change, y2_change) if value is not None],
        default=None,
    )
    if rate_pressure is not None and rate_pressure >= 0.40:
        signals.append(
            {
                "signal_name": "discount_rate_pressure",
                "value": rate_pressure,
                "strength": "strong" if rate_pressure >= 0.75 else "moderate",
                "direction": "risk_off",
                "interpretation": (
                    "Recent yield increases raise discount-rate pressure on duration assets."
                ),
            }
        )

    real_yield = _to_float(row.get("real_yield_10y"))
    if real_yield is not None and real_yield >= 1.75:
        signals.append(
            {
                "signal_name": "real_yield_pressure",
                "value": real_yield,
                "strength": "strong" if real_yield >= 2.25 else "moderate",
                "direction": "risk_off",
                "interpretation": "Elevated real yields tighten financial conditions.",
            }
        )

    hy_spread = _to_float(row.get("high_yield_spread"))
    if hy_spread is not None and hy_spread >= 5.0:
        signals.append(
            {
                "signal_name": "credit_stress",
                "value": hy_spread,
                "strength": "strong" if hy_spread >= 7.0 else "moderate",
                "direction": "risk_off",
                "interpretation": "High-yield spreads indicate rising credit stress.",
            }
        )

    rate_regime = str(row.get("rate_regime") or "")
    slope_change = None
    if y10_change is not None and y2_change is not None:
        slope_change = y10_change - y2_change
    if rate_regime == "bull_steepening":
        signals.append(
            {
                "signal_name": "bull_steepening",
                "value": slope_change,
                "strength": (
                    "strong" if slope_change is not None and slope_change >= 0.50 else "moderate"
                ),
                "direction": "risk_on",
                "interpretation": "Front-end yields are falling faster than long yields.",
            }
        )
    elif rate_regime == "bear_steepening":
        signals.append(
            {
                "signal_name": "bear_steepening",
                "value": slope_change,
                "strength": (
                    "strong" if slope_change is not None and slope_change >= 0.50 else "moderate"
                ),
                "direction": "risk_off",
                "interpretation": "Long yields are rising faster than front-end yields.",
            }
        )

    return signals
