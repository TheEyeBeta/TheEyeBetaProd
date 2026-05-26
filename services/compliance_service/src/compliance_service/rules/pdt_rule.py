"""Pattern Day Trader rule for US accounts under $25k equity."""

from __future__ import annotations

from datetime import UTC, datetime

from compliance_service.models import ComplianceMandate, OrderProposal, PortfolioContext, RuleResult
from compliance_service.rules.base import ComplianceRule, block_result, pass_result

PDT_EQUITY_THRESHOLD_USD = 25_000.0


class PdtRule(ComplianceRule):
    """Block day trades when PDT limits would be exceeded on sub-$25k US accounts."""

    rule_id = "pdt_rule"

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        _ = mandate
        if order.market.upper() != "US":
            return pass_result(self.rule_id, "PDT rule applies to US accounts only")
        if portfolio.equity_usd >= PDT_EQUITY_THRESHOLD_USD:
            return pass_result(
                self.rule_id,
                f"equity {portfolio.equity_usd:.0f} >= {PDT_EQUITY_THRESHOLD_USD:.0f}",
            )

        would_day_trade = self._is_day_trade(order, portfolio)
        if not would_day_trade:
            return pass_result(self.rule_id, "order is not a day trade")

        if portfolio.day_trades_5d >= mandate.max_day_trades_5d:
            return block_result(
                self.rule_id,
                (
                    f"PDT limit: {portfolio.day_trades_5d} day trades in 5d "
                    f"(max {mandate.max_day_trades_5d}) with equity "
                    f"${portfolio.equity_usd:.0f}"
                ),
            )
        return pass_result(self.rule_id, "day trade within PDT allowance")

    def _is_day_trade(self, order: OrderProposal, portfolio: PortfolioContext) -> bool:
        """Heuristic: opposite-side activity today on the same instrument."""
        for prior in portfolio.recent_orders:
            if prior.instrument_id != order.instrument_id:
                continue
            if prior.side.lower() == order.side.lower():
                continue
            if prior.created_at.date() == datetime.now(tz=UTC).date():
                return True
        return False
