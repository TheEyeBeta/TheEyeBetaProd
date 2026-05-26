"""AML structuring heuristic."""

from __future__ import annotations

from datetime import UTC, datetime

from compliance_service.models import ComplianceMandate, OrderProposal, PortfolioContext, RuleResult
from compliance_service.rules.base import ComplianceRule, block_result, pass_result


class AmlStructuringRule(ComplianceRule):
    """Flag many sub-threshold trades on the same instrument in one day."""

    rule_id = "aml_structuring"

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        today = datetime.now(tz=UTC).date()
        notional = order.qty * order.limit_price
        small_today = 0
        if notional < mandate.aml_small_trade_usd:
            small_today = 1

        for prior in portfolio.recent_orders:
            if prior.instrument_id != order.instrument_id:
                continue
            if prior.created_at.date() != today:
                continue
            price = prior.limit_price or order.limit_price
            if prior.qty * price < mandate.aml_small_trade_usd:
                small_today += 1

        if small_today >= mandate.aml_small_trade_count:
            return block_result(
                self.rule_id,
                (
                    f"structuring heuristic: {small_today} sub-"
                    f"${mandate.aml_small_trade_usd:.0f} trades today on "
                    f"instrument {order.instrument_id}"
                ),
            )
        return pass_result(self.rule_id, "no structuring pattern detected")
