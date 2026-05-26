"""pytest fixtures for compliance-service."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from zinc_schemas.restricted import RestrictedEntry, RestrictedListDocument

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from compliance_service.models import (  # noqa: E402
    ComplianceMandate,
    OrderProposal,
    PortfolioContext,
    RecentOrder,
)

PORTFOLIO_ID = "660e8400-e29b-41d4-a716-446655440099"
NOW = datetime.now(tz=UTC)


@pytest.fixture
def base_mandate() -> ComplianceMandate:
    """Default compliance mandate."""
    return ComplianceMandate(
        no_hk_dual_class=True,
        blocked_markets=["RU"],
        max_day_trades_5d=3,
        aml_small_trade_usd=10_000.0,
        aml_small_trade_count=3,
    )


@pytest.fixture
def base_portfolio() -> PortfolioContext:
    """US paper account with moderate equity."""
    return PortfolioContext(
        portfolio_id=PORTFOLIO_ID,
        account_id="880e8400-e29b-41d4-a716-446655440003",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=20_000.0,
        day_trades_5d=3,
        recent_orders=[],
        instrument_metadata={"sector": "technology"},
    )


@pytest.fixture
def base_order() -> OrderProposal:
    """Small US equity buy."""
    return OrderProposal(
        instrument_id=1,
        symbol="AAPL",
        side="buy",
        qty=10.0,
        limit_price=100.0,
        market="US",
        order_id="990e8400-e29b-41d4-a716-446655440099",
    )


@pytest.fixture
def restricted_document() -> RestrictedListDocument:
    """Minimal restricted list for unit tests."""
    return RestrictedListDocument(
        sanctions=[RestrictedEntry(symbol="SANCTIONED", list_type="blacklist", reason="OFAC")],
        insider_restricted=[
            RestrictedEntry(symbol="GREYCO", list_type="grey_list", reason="insider pending"),
            RestrictedEntry(symbol="WATCHCO", list_type="watch_list", reason="watch"),
        ],
    )


def recent_sell_loss(*, instrument_id: int = 1, days_ago: int = 5) -> RecentOrder:
    """Recent loss-making sell for wash-sale tests."""
    return RecentOrder(
        instrument_id=instrument_id,
        side="sell",
        qty=50.0,
        limit_price=95.0,
        created_at=NOW - timedelta(days=days_ago),
        realized_pnl=-500.0,
    )
