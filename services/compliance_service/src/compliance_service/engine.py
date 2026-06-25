"""Ordered compliance rule engine."""

from __future__ import annotations

from typing import Any

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


def _aggregate(rule_results: list[RuleResult]) -> tuple[ComplianceOutcome, list[str], str]:
    aggregate = ComplianceOutcome.PASS
    failed: list[str] = []
    for hit in rule_results:
        if hit.outcome == ComplianceOutcome.BLOCK:
            aggregate = ComplianceOutcome.BLOCK
            failed.append(hit.rule_id)
        elif hit.outcome == ComplianceOutcome.WARN and aggregate == ComplianceOutcome.PASS:
            aggregate = ComplianceOutcome.WARN
            failed.append(hit.rule_id)
    reason = "all rules passed"
    if failed:
        reason = "; ".join(r.detail for r in rule_results if r.rule_id in failed)
    return aggregate, failed, reason


def apply_admin_overrides_and_holds(
    result: ComplianceCheckResult,
    *,
    holds: list[dict[str, Any]],
    overrides_by_rule: dict[str, dict[str, Any]],
) -> ComplianceCheckResult:
    """Downgrade overridden rule hits to PASS, then force BLOCK for any active legal hold.

    Legal holds are absolute and are applied after overrides — an override can never
    suppress a legal hold.
    """
    rule_results: list[RuleResult] = []
    for hit in result.rule_results:
        override = overrides_by_rule.get(hit.rule_id)
        if override and hit.outcome != ComplianceOutcome.PASS:
            rule_results.append(
                RuleResult(
                    rule_id=hit.rule_id,
                    outcome=ComplianceOutcome.PASS,
                    detail=(
                        f"override by {override['actor']} ({override['reason']}): {hit.detail}"
                    ),
                ),
            )
        else:
            rule_results.append(hit)

    if holds:
        hold = holds[0]
        rule_results.append(
            RuleResult(
                rule_id="legal_hold",
                outcome=ComplianceOutcome.BLOCK,
                detail=(
                    f"legal hold on {hold['entity_type']} {hold['entity_id']}: "
                    f"{hold['reason']} (placed by {hold['placed_by']})"
                ),
            ),
        )

    outcome, failed, reason = _aggregate(rule_results)
    return ComplianceCheckResult(
        outcome=outcome,
        reason=reason,
        rule_results=rule_results,
        failed_rules=failed,
    )
