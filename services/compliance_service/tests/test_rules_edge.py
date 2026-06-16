"""Edge-case tests for compliance rules (PDT, wash sale, AML, restricted list)."""

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

from compliance_service.models import (  # noqa: E402
    ComplianceOutcome,
    OrderProposal,
    PortfolioContext,
    RecentOrder,
)
from compliance_service.rules.aml_structuring import AmlStructuringRule  # noqa: E402
from compliance_service.rules.pdt_rule import PdtRule  # noqa: E402
from compliance_service.rules.restricted_list import RestrictedListRule  # noqa: E402
from compliance_service.rules.wash_sale import WashSaleRule  # noqa: E402
from zinc_schemas.restricted import RestrictedEntry, RestrictedListDocument  # noqa: E402


@pytest.mark.unit
def test_pdt_blocks_fourth_day_trade(
    base_order: OrderProposal,
    base_mandate,
) -> None:
    """Fourth day trade in 5 days is blocked for sub-$25k accounts."""
    rule = PdtRule()
    portfolio = PortfolioContext(
        portfolio_id="p1",
        account_id="a1",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=20_000.0,
        day_trades_5d=3,
        recent_orders=[
            RecentOrder(
                instrument_id=1,
                side="sell",
                qty=10.0,
                limit_price=100.0,
                created_at=NOW,
                realized_pnl=0.0,
            ),
        ],
        instrument_metadata={},
    )
    result = rule.check(base_order, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK


@pytest.mark.unit
def test_pdt_allows_third_day_trade(
    base_order: OrderProposal,
    base_mandate,
) -> None:
    """Exactly three day trades in 5 days is allowed."""
    rule = PdtRule()
    portfolio = PortfolioContext(
        portfolio_id="p1",
        account_id="a1",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=20_000.0,
        day_trades_5d=2,
        recent_orders=[
            RecentOrder(
                instrument_id=1,
                side="sell",
                qty=10.0,
                limit_price=100.0,
                created_at=NOW,
                realized_pnl=0.0,
            ),
        ],
        instrument_metadata={},
    )
    result = rule.check(base_order, portfolio, base_mandate)
    assert result.outcome != ComplianceOutcome.BLOCK


@pytest.mark.unit
def test_wash_sale_blocks_repurchase_within_30_days(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate,
) -> None:
    """Repurchase within 30 days of loss sell is blocked."""
    rule = WashSaleRule()
    portfolio = replace(
        base_portfolio,
        recent_orders=[recent_sell_loss(instrument_id=1, days_ago=10)],
    )
    result = rule.check(base_order, portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK


@pytest.mark.unit
def test_restricted_list_case_insensitive(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate,
) -> None:
    """Restricted list matches case-insensitively."""
    doc = RestrictedListDocument(
        sanctions=[RestrictedEntry(symbol="aapl", list_type="blacklist", reason="test")],
        insider_restricted=[],
    )
    rule = RestrictedListRule(doc)
    order = replace(base_order, symbol="AAPL")
    result = rule.check(order, base_portfolio, base_mandate)
    assert result.outcome == ComplianceOutcome.BLOCK


@pytest.mark.unit
def test_aml_structuring_flags_small_trades(
    base_order: OrderProposal,
    base_portfolio: PortfolioContext,
    base_mandate,
) -> None:
    """Multiple sub-threshold orders within 24h are flagged."""
    rule = AmlStructuringRule()
    small = replace(base_order, qty=50.0, limit_price=150.0)
    portfolio = replace(
        base_portfolio,
        recent_orders=[
            RecentOrder(
                instrument_id=1,
                side="buy",
                qty=50.0,
                limit_price=150.0,
                created_at=NOW - timedelta(hours=2),
                realized_pnl=0.0,
            ),
            RecentOrder(
                instrument_id=1,
                side="buy",
                qty=50.0,
                limit_price=150.0,
                created_at=NOW - timedelta(hours=4),
                realized_pnl=0.0,
            ),
        ],
    )
    result = rule.check(small, portfolio, base_mandate)
    assert result.outcome in {ComplianceOutcome.BLOCK, ComplianceOutcome.WARN}
