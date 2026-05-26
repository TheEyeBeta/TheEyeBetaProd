"""Ordered compliance rule engine."""

from __future__ import annotations

from compliance_service.models import (
    ComplianceCheckResult,
    ComplianceMandate,
    ComplianceOutcome,
    OrderProposal,
    PortfolioContext,
    RuleResult,
)
from compliance_service.rules import DEFAULT_RULES
from compliance_service.rules.base import ComplianceRule


class ComplianceEngine:
    """Run five Part 9.2 rule groups in fixed order."""

    def __init__(self, rules: list[ComplianceRule] | None = None) -> None:
        self._rules = rules or list(DEFAULT_RULES)

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> ComplianceCheckResult:
        """Evaluate all rules and aggregate the outcome."""
        results: list[RuleResult] = []
        aggregate = ComplianceOutcome.PASS
        failed: list[str] = []

        for rule in self._rules:
            hit = rule.check(order, portfolio, mandate)
            results.append(hit)
            if hit.outcome == ComplianceOutcome.BLOCK:
                aggregate = ComplianceOutcome.BLOCK
                failed.append(hit.rule_id)
            elif hit.outcome == ComplianceOutcome.WARN and aggregate == ComplianceOutcome.PASS:
                aggregate = ComplianceOutcome.WARN
                failed.append(hit.rule_id)

        reason = "all rules passed"
        if failed:
            reason = "; ".join(r.detail for r in results if r.rule_id in failed)

        return ComplianceCheckResult(
            outcome=aggregate,
            reason=reason,
            rule_results=results,
            failed_rules=failed,
        )
