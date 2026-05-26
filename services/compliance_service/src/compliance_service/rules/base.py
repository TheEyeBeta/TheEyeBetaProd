"""Compliance rule base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from compliance_service.models import (
    ComplianceMandate,
    ComplianceOutcome,
    OrderProposal,
    PortfolioContext,
    RuleResult,
)


class ComplianceRule(ABC):
    """One Part 9.2 rule group."""

    rule_id: str

    @abstractmethod
    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        """Evaluate the rule and return a structured outcome."""


def pass_result(rule_id: str, detail: str) -> RuleResult:
    """Helper for a passing rule."""
    return RuleResult(rule_id=rule_id, outcome=ComplianceOutcome.PASS, detail=detail)


def warn_result(rule_id: str, detail: str) -> RuleResult:
    """Helper for a warning rule."""
    return RuleResult(rule_id=rule_id, outcome=ComplianceOutcome.WARN, detail=detail)


def block_result(rule_id: str, detail: str) -> RuleResult:
    """Helper for a blocking rule."""
    return RuleResult(rule_id=rule_id, outcome=ComplianceOutcome.BLOCK, detail=detail)
