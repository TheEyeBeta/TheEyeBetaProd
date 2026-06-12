"""Pure macro calculations shared by workers and tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

ObservationPoint = tuple[object, float]


def compute_month_over_month_diff(points: Sequence[ObservationPoint]) -> list[ObservationPoint]:
    """Return consecutive month-over-month differences for sorted level observations."""
    diffs: list[ObservationPoint] = []
    for previous, current in zip(points, points[1:], strict=False):
        diffs.append((current[0], current[1] - previous[1]))
    return diffs


def compute_yoy_percent(
    points: Sequence[ObservationPoint],
    *,
    periods_per_year: int = 12,
) -> list[ObservationPoint]:
    """Return year-over-year percent changes for sorted monthly index observations."""
    changes: list[ObservationPoint] = []
    for index in range(periods_per_year, len(points)):
        current_date, current_value = points[index]
        _, year_ago_value = points[index - periods_per_year]
        if year_ago_value > 0:
            changes.append((current_date, (current_value / year_ago_value - 1.0) * 100.0))
    return changes


def annualized_qoq_pct(current_gdp: float | None, prior_quarter_gdp: float | None) -> float | None:
    """Return annualised quarter-on-quarter GDP growth percentage."""
    if current_gdp is None or prior_quarter_gdp is None or prior_quarter_gdp <= 0:
        return None
    return ((current_gdp / prior_quarter_gdp) ** 4 - 1.0) * 100.0


def classify_rate_environment(fed_funds_change_30d: float | None) -> str:
    """Classify rates using a 30d threshold rescaled from the old 10bps/90d spec."""
    if fed_funds_change_30d is None:
        return "unknown"
    if fed_funds_change_30d > 0.05:
        return "hiking"
    if fed_funds_change_30d < -0.05:
        return "cutting"
    return "neutral"


def classify_yield_curve(spread_2s10s: float | None) -> str:
    """Classify the 2s10s curve using percentage-point spread thresholds."""
    if spread_2s10s is None:
        return "unknown"
    if spread_2s10s > 1.50:
        return "steep"
    if spread_2s10s > 0.50:
        return "normal"
    if spread_2s10s < 0.0:
        return "inverted"
    return "flat"


def classify_credit_environment(hy_oas_bps: float | None) -> str:
    """Classify credit spreads with labels allowed by the live CHECK constraint."""
    if hy_oas_bps is None:
        return "unknown"
    if hy_oas_bps < 350:
        return "tight"
    if hy_oas_bps > 600:
        return "stressed"
    if hy_oas_bps > 450:
        return "wide"
    return "normal"


def classify_volatility_regime(vix: float | None) -> str:
    """Classify VIX with labels allowed by the live CHECK constraint."""
    if vix is None:
        return "unknown"
    if vix < 15:
        return "calm"
    if vix < 25:
        return "elevated"
    if vix < 40:
        return "stressed"
    return "crisis"


def classify_dollar_regime(dxy_change_30d: float | None) -> str:
    """Classify 30d DXY move."""
    if dxy_change_30d is None:
        return "unknown"
    if dxy_change_30d > 1.5:
        return "strong"
    if dxy_change_30d < -1.5:
        return "weak"
    return "neutral"


def compute_style_tilts(
    rate_env: str,
    yield_curve: str,
    credit_env: str,
    vol_regime: str,
    dollar_regime: str,
) -> dict[str, object]:
    """Compute scoring weight multipliers and clamp each weight to [0.70, 1.40]."""
    tilts: dict[str, object] = {
        "momentum_weight": 1.0,
        "valuation_weight": 1.0,
        "quality_weight": 1.0,
        "risk_weight": 1.0,
        "growth_weight": 1.0,
        "notes": [],
    }
    notes = tilts["notes"]
    assert isinstance(notes, list)

    if rate_env == "cutting":
        tilts["growth_weight"] = 1.15
        tilts["valuation_weight"] = 1.10
        notes.append("rate_cutting: overweight growth+valuation")
    elif rate_env == "hiking":
        tilts["growth_weight"] = 0.85
        tilts["quality_weight"] = 1.15
        notes.append("rate_hiking: overweight quality, underweight growth")

    if yield_curve == "inverted":
        tilts["risk_weight"] = 1.20
        tilts["momentum_weight"] = 0.90
        notes.append("inverted_curve: risk-off, underweight momentum")

    if credit_env == "stressed":
        tilts["quality_weight"] = max(float(tilts["quality_weight"]), 1.20)
        tilts["risk_weight"] = max(float(tilts["risk_weight"]), 1.30)
        notes.append("stressed_credit: strongly overweight quality+defensive")
    elif credit_env == "wide":
        tilts["quality_weight"] = max(float(tilts["quality_weight"]), 1.10)
        tilts["risk_weight"] = max(float(tilts["risk_weight"]), 1.15)
        notes.append("wide_credit: mild defensive tilt")
    elif credit_env == "tight":
        tilts["momentum_weight"] = max(float(tilts["momentum_weight"]), 1.10)
        notes.append("tight_credit: mild momentum tilt")

    if vol_regime in ("stressed", "crisis"):
        tilts["risk_weight"] = max(float(tilts["risk_weight"]), 1.30)
        tilts["momentum_weight"] = min(float(tilts["momentum_weight"]), 0.80)
        notes.append(f"vol_{vol_regime}: defensive tilt, reduce momentum")
    elif vol_regime == "calm":
        tilts["momentum_weight"] = min(float(tilts["momentum_weight"]) * 1.05, 1.20)

    if dollar_regime == "strong":
        notes.append("strong_dollar: favour domestic-revenue companies")
    elif dollar_regime == "weak":
        notes.append("weak_dollar: favour multinational/commodity exposure")

    for key in [
        "momentum_weight",
        "valuation_weight",
        "quality_weight",
        "risk_weight",
        "growth_weight",
    ]:
        tilts[key] = round(max(0.70, min(1.40, float(tilts[key]))), 4)

    tilts["computed_at"] = datetime.now(tz=UTC).isoformat()
    return tilts

