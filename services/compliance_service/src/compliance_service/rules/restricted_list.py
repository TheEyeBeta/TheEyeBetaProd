"""Restricted-list rule (sanctions + insider lists)."""

from __future__ import annotations

from compliance_service.models import (
    ComplianceMandate,
    OrderProposal,
    PortfolioContext,
    RuleResult,
)
from compliance_service.rules.base import ComplianceRule, block_result, pass_result, warn_result
from zinc_schemas.restricted import RestrictedListDocument, load_restricted_list


class RestrictedListRule(ComplianceRule):
    """Block or warn on symbols present in ``restricted.yaml``."""

    rule_id = "restricted_list"

    def __init__(self, document: RestrictedListDocument | None = None) -> None:
        self._document = document or load_restricted_list()

    def check(
        self,
        order: OrderProposal,
        portfolio: PortfolioContext,
        mandate: ComplianceMandate,
    ) -> RuleResult:
        _ = portfolio, mandate
        entry = self._document.lookup(order.symbol)
        if entry is None:
            return pass_result(self.rule_id, f"{order.symbol} not on restricted lists")
        if entry.list_type == "blacklist":
            return block_result(
                self.rule_id,
                f"{order.symbol} on {entry.list_type}: {entry.reason}",
            )
        if entry.list_type == "grey_list":
            return warn_result(
                self.rule_id,
                f"{order.symbol} on grey_list: {entry.reason}; override required",
            )
        return warn_result(
            self.rule_id,
            f"{order.symbol} on watch_list: {entry.reason}",
        )
