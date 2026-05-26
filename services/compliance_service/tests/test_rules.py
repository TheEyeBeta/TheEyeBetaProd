"""Unit tests for each Part 9.2 compliance rule."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from conftest import NOW, recent_sell_loss  # noqa: E402

from compliance_service.models import (
    ComplianceMandate,
    ComplianceOutcome,
    OrderProposal,
    PortfolioContext,
    RecentOrder,
)
from compliance_service.rules.aml_structuring import AmlStructuringRule
from compliance_service.rules.mandate_constraints import MandateConstraintsRule
from compliance_service.rules.pdt_rule import PdtRule
from compliance_service.rules.restricted_list import RestrictedListRule
from compliance_service.rules.wash_sale import WashSaleRule
from zinc_schemas.restricted import RestrictedListDocument


@pytest.mark.unit
def test_restricted_list_blocks_sanctioned(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
    restricted_document: RestrictedListDocument,
) -> None:
    rule = RestrictedListRule(restricted_document)
    order = replace(base_order, symbol="SANCTIONED")
    result = rule.check(order, base_portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.rule_id == "restricted_list"


@pytest.mark.unit
def test_restricted_list_warns_grey_list(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
    restricted_document: RestrictedListDocument,
) -> None:
    rule = RestrictedListRule(restricted_document)
    order = replace(base_order, symbol="GREYCO")
    result = rule.check(order, base_portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.WARN


@pytest.mark.unit
def test_mandate_blocks_hk_dual_class(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
) -> None:
    rule = MandateConstraintsRule()
    portfolio = replace(
        base_portfolio,
        instrument_metadata={"dual_class_hk": True, "share_class": "B"},
    )
    order = replace(base_order, symbol="0700")
    result = rule.check(order, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK


@pytest.mark.unit
def test_wash_sale_blocks_us_buy_after_loss_sell(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
) -> None:
    rule = WashSaleRule()
    portfolio = replace(base_portfolio, recent_orders=[recent_sell_loss()])
    result = rule.check(base_order, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.rule_id == "wash_sale"


@pytest.mark.unit
def test_pdt_blocks_sub_25k_day_trade(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
) -> None:
    rule = PdtRule()
    portfolio = replace(
        base_portfolio,
        equity_usd=20_000.0,
        day_trades_5d=3,
        recent_orders=[
            RecentOrder(
                instrument_id=1,
                side="sell",
                qty=5.0,
                limit_price=100.0,
                created_at=NOW,
            ),
        ],
    )
    result = rule.check(base_order, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.rule_id == "pdt_rule"


@pytest.mark.unit
def test_aml_structuring_blocks_many_small_trades(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate: ComplianceMandate,
) -> None:
    rule = AmlStructuringRule()
    small = OrderProposal(
        instrument_id=1,
        symbol="AAPL",
        side="buy",
        qty=50.0,
        limit_price=100.0,
        market="US",
    )
    prior = [
        RecentOrder(
            instrument_id=1,
            side="buy",
            qty=50.0,
            limit_price=100.0,
            created_at=NOW - timedelta(hours=2),
        ),
        RecentOrder(
            instrument_id=1,
            side="buy",
            qty=40.0,
            limit_price=100.0,
            created_at=NOW - timedelta(hours=1),
        ),
    ]
    portfolio = replace(base_portfolio, recent_orders=prior)
    result = rule.check(small, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.rule_id == "aml_structuring"
