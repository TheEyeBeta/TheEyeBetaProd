"""Portfolio mandate compliance constraints."""

from __future__ import annotations

from compliance_service.models import ComplianceMandate, OrderProposal, PortfolioContext, RuleResult
from compliance_service.rules.base import ComplianceRule, block_result, pass_result


class MandateConstraintsRule(ComplianceRule):
    """Enforce mandate JSON constraints such as no HK dual-class shares."""

    rule_id = "mandate_constraints"

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        market = order.market.upper()
        if market in {m.upper() for m in mandate.blocked_markets}:
            return block_result(
                self.rule_id,
                f"market {market} blocked by portfolio mandate",
            )

        metadata = portfolio.instrument_metadata
        if mandate.no_hk_dual_class and metadata.get("dual_class_hk") is True:
            return block_result(
                self.rule_id,
                f"{order.symbol} is HK dual-class; prohibited by mandate",
            )

        if mandate.no_hk_dual_class and metadata.get("exchange") == "HKEX":
            share_class = str(metadata.get("share_class", "")).upper()
            if share_class in {"B", "CLASS_B", "DUAL"}:
                return block_result(
                    self.rule_id,
                    f"{order.symbol} HK dual-class share class {share_class} prohibited",
                )

        return pass_result(self.rule_id, "mandate constraints satisfied")
