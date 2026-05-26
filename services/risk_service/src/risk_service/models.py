"""Risk-service models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class RiskOutcome(IntEnum):
    """Pre-trade risk decision."""

    ALLOW = 0
    WARN = 1
    BLOCK = 2


class PortfolioMandate(BaseModel):
    """Portfolio risk mandate parsed from ``portfolios.mandate`` jsonb."""

    model_config = ConfigDict(extra="ignore")

    max_position_pct: float = Field(default=0.10, ge=0, le=1)
    max_sector_pct: float = Field(default=0.35, ge=0, le=1)
    max_correlation_cluster_pct: float = Field(default=0.40, ge=0, le=1)
    max_var: float = Field(default=0.05, ge=0, description="Max 95% VaR as NAV fraction")
    max_drawdown_pct: float = Field(default=0.15, ge=0, le=1)
    max_hhi: float = Field(default=0.30, ge=0, le=1)


@dataclass(frozen=True)
class PositionRow:
    """One open position."""

    instrument_id: int
    symbol: str
    sector: str
    cluster: str
    qty: float
    market_value: float


@dataclass(frozen=True)
class OrderProposal:
    """Proposed order for pre-trade checks."""

    instrument_id: int
    side: str
    qty: float
    price: float
    sector: str
    cluster: str
    order_intent: str = "BUY"


@dataclass
class PortfolioRiskContext:
    """Inputs for the six ordered pre-trade checks."""

    portfolio_id: str
    nav: float
    mandate: PortfolioMandate
    positions: list[PositionRow]
    return_samples: np.ndarray
    wealth_30d: np.ndarray
    cluster_exposures: dict[str, float] = field(default_factory=dict)
    beta_spy: float = 1.0


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single risk check."""

    name: str
    outcome: RiskOutcome
    detail: str
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskValidationResult:
    """Aggregate validation outcome."""

    outcome: RiskOutcome
    reason: str
    failed_checks: list[str]
    metrics: dict[str, float]
    check_results: list[CheckResult]

    @property
    def approved(self) -> bool:
        return self.outcome != RiskOutcome.BLOCK


@dataclass(frozen=True)
class ComputedPortfolioMetrics:
    """Snapshot written to ``risk_metrics``."""

    portfolio_id: str
    var_95: float
    cvar_95: float
    max_drawdown: float
    gross_exposure: float
    net_exposure: float
    beta_spy: float
    concentration_hhi: float
    raw: dict[str, Any] = field(default_factory=dict)
