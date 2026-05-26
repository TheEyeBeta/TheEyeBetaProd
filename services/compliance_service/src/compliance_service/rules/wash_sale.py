"""US wash-sale rule (30-day window)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from compliance_service.models import ComplianceMandate, OrderProposal, PortfolioContext, RuleResult
from compliance_service.rules.base import ComplianceRule, block_result, pass_result


class WashSaleRule(ComplianceRule):
    """Block US buys within 30 days of a loss-making sell on the same instrument."""

    rule_id = "wash_sale"
    window_days = 30

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        _ = mandate
        if order.market.upper() != "US" or order.side.lower() != "buy":
            return pass_result(self.rule_id, "wash-sale rule not applicable")

        cutoff = datetime.now(tz=UTC) - timedelta(days=self.window_days)
        for prior in portfolio.recent_orders:
            if prior.instrument_id != order.instrument_id:
                continue
            if prior.side.lower() != "sell":
                continue
            if prior.created_at < cutoff:
                continue
            pnl = prior.realized_pnl
            if pnl is not None and pnl < 0:
                return block_result(
                    self.rule_id,
                    (
                        f"wash-sale: loss-making sell within {self.window_days}d "
                        f"on instrument {order.instrument_id}"
                    ),
                )
        return pass_result(self.rule_id, "no wash-sale conflict")
