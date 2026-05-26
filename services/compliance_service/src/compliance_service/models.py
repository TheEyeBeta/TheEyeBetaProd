"""Compliance-service models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ComplianceOutcome(IntEnum):
    """Aggregate compliance decision."""

    PASS = 0
    WARN = 1
    BLOCK = 2

    def db_value(self) -> str:
        """Return lowercase value for ``compliance_checks.outcome``."""
        return self.name.lower()


class ComplianceMandate(BaseModel):
    """Portfolio compliance constraints from ``portfolios.mandate`` jsonb."""

    model_config = ConfigDict(extra="ignore")

    no_hk_dual_class: bool = Field(default=False)
    blocked_markets: list[str] = Field(default_factory=list)
    max_day_trades_5d: int = Field(default=3, ge=0)
    aml_small_trade_usd: float = Field(default=10_000.0, ge=0)
    aml_small_trade_count: int = Field(default=3, ge=1)


@dataclass(frozen=True)
class OrderProposal:
    """Order under compliance review."""

    instrument_id: int
    symbol: str
    side: str
    qty: float
    limit_price: float
    market: str
    order_id: str | None = None


@dataclass(frozen=True)
class RecentOrder:
    """Historical order for wash-sale and AML heuristics."""

    instrument_id: int
    side: str
    qty: float
    limit_price: float | None
    created_at: datetime
    realized_pnl: float | None = None


@dataclass(frozen=True)
class PortfolioContext:
    """Portfolio and account context for rule evaluation."""

    portfolio_id: str
    account_id: str
    broker: str
    account_mode: str
    base_currency: str
    equity_usd: float
    day_trades_5d: int
    recent_orders: list[RecentOrder] = field(default_factory=list)
    instrument_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleResult:
    """Outcome of one compliance rule."""

    rule_id: str
    outcome: ComplianceOutcome
    detail: str


@dataclass(frozen=True)
class ComplianceCheckResult:
    """Aggregate result across all rule groups."""

    outcome: ComplianceOutcome
    reason: str
    rule_results: list[RuleResult]
    failed_rules: list[str]

    @property
    def approved(self) -> bool:
        return self.outcome != ComplianceOutcome.BLOCK

    @property
    def blocking_rule_id(self) -> str | None:
        for result in self.rule_results:
            if result.outcome == ComplianceOutcome.BLOCK:
                return result.rule_id
        return None
