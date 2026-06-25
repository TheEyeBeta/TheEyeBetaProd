"""Risk control gaps and default limit schema."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LIMITS: dict[str, float] = {
    "max_position_pct": 0.10,
    "max_sector_pct": 0.35,
    "max_correlation_cluster_pct": 0.40,
    "max_var": 0.05,
    "max_drawdown_pct": 0.15,
    "max_hhi": 0.30,
}

STALE_METRICS_HOURS = 24


@dataclass(frozen=True, slots=True)
class RiskControlGap:
    action: str
    reason: str


LIMIT_EDIT_GAP = RiskControlGap(
    action="edit_limits",
    reason=(
        "Limit patches persist in admin_risk_limits only; "
        "risk_service validator still reads portfolios.mandate until wired."
    ),
)

TRADING_LOCK_GAP = RiskControlGap(
    action="trading_lock",
    reason=(
        "Risk trading lock is recorded in admin_risk_state; "
        "OMS/broker enforce via Emergency Trading halt for production stops."
    ),
)
