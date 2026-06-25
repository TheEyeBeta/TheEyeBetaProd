"""Tests for CheckOrder orchestration and persistence."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from zinc_proto import compliance_pb2

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from compliance_service.engine import ComplianceEngine  # noqa: E402
from compliance_service.models import (  # noqa: E402
    ComplianceMandate,
    ComplianceOutcome,
    OrderProposal,
    PortfolioContext,
    RuleResult,
)
from compliance_service.rules.restricted_list import RestrictedListRule  # noqa: E402
from zinc_schemas.restricted import RestrictedEntry, RestrictedListDocument  # noqa: E402


@pytest.mark.unit
def test_engine_runs_rules_in_order() -> None:
    """Engine executes five rules and aggregates BLOCK."""
    doc = RestrictedListDocument(
        sanctions=[RestrictedEntry(symbol="BAD", list_type="blacklist", reason="test")],
    )
    engine = ComplianceEngine(rules=[RestrictedListRule(doc)])
    order = OrderProposal(1, "BAD", "buy", 1, 100, "US")
    portfolio = PortfolioContext("p", "a", "alpaca", "paper", "USD", 50_000, 0)
    mandate = ComplianceMandate()
    result = engine.check(order, portfolio, mandate)
    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.failed_rules == ["restricted_list"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_order_persists_rows_and_rejects_order() -> None:
    """CheckOrder writes compliance_checks and rejects blocked orders."""
    from compliance_service.app import check_order_request

    portfolio = PortfolioContext(
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        account_id="acct",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=50_000.0,
        day_trades_5d=0,
    )
    mandate = ComplianceMandate()
    order_id = "990e8400-e29b-41d4-a716-446655440099"
    doc = RestrictedListDocument(
        sanctions=[RestrictedEntry(symbol="BLOCKME", list_type="blacklist", reason="test")],
    )
    engine = ComplianceEngine(rules=[RestrictedListRule(doc)])

    request = compliance_pb2.ComplianceCheckRequest(
        order_id=order_id,
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        instrument_id=1,
        symbol="BLOCKME",
        side="buy",
        qty=10,
        limit_price=100,
        market="US",
    )

    mock_persist = AsyncMock()
    mock_reject = AsyncMock()

    with (
        patch(
            "compliance_service.app.load_check_context",
            AsyncMock(return_value=(portfolio, mandate, "BLOCKME")),
        ),
        patch(
            "compliance_service.app.load_active_holds_and_overrides",
            AsyncMock(return_value=([], {})),
        ),
        patch("compliance_service.app.persist_compliance_checks", mock_persist),
        patch("compliance_service.app.reject_order_if_blocked", mock_reject),
        patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/db"}, clear=False
        ),
    ):
        result = await check_order_request(engine, request)

    assert result.outcome == ComplianceOutcome.BLOCK
    mock_persist.assert_awaited_once()
    assert mock_persist.await_args.kwargs["order_id"] == order_id
    assert len(mock_persist.await_args.kwargs["results"]) == 1
    mock_reject.assert_awaited_once()
    assert mock_reject.await_args.kwargs["rule_id"] == "restricted_list"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_order_override_downgrades_block_to_pass() -> None:
    """An active admin override on the failing rule approves the order."""
    from compliance_service.app import check_order_request

    portfolio = PortfolioContext(
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        account_id="acct",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=50_000.0,
        day_trades_5d=0,
    )
    mandate = ComplianceMandate()
    doc = RestrictedListDocument(
        sanctions=[RestrictedEntry(symbol="BLOCKME", list_type="blacklist", reason="test")],
    )
    engine = ComplianceEngine(rules=[RestrictedListRule(doc)])

    request = compliance_pb2.ComplianceCheckRequest(
        order_id="990e8400-e29b-41d4-a716-446655440099",
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        instrument_id=1,
        symbol="BLOCKME",
        side="buy",
        qty=10,
        limit_price=100,
        market="US",
    )

    with (
        patch(
            "compliance_service.app.load_check_context",
            AsyncMock(return_value=(portfolio, mandate, "BLOCKME")),
        ),
        patch(
            "compliance_service.app.load_active_holds_and_overrides",
            AsyncMock(
                return_value=(
                    [],
                    {
                        "restricted_list": {
                            "portfolio_id": portfolio.portfolio_id,
                            "rule_id": "restricted_list",
                            "reason": "manual clearance",
                            "actor": "ops@theeyebeta.com",
                            "expires_at": None,
                        },
                    },
                ),
            ),
        ),
        patch("compliance_service.app.persist_compliance_checks", AsyncMock()),
        patch("compliance_service.app.reject_order_if_blocked", AsyncMock()),
        patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/db"}, clear=False
        ),
    ):
        result = await check_order_request(engine, request)

    assert result.outcome == ComplianceOutcome.PASS
    assert result.approved is True
    assert result.failed_rules == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_order_legal_hold_blocks_even_when_rules_pass() -> None:
    """An active legal hold blocks the order regardless of rule outcomes."""
    from compliance_service.app import check_order_request

    portfolio = PortfolioContext(
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        account_id="acct",
        broker="alpaca",
        account_mode="paper",
        base_currency="USD",
        equity_usd=50_000.0,
        day_trades_5d=0,
    )
    mandate = ComplianceMandate()
    doc = RestrictedListDocument(sanctions=[])
    engine = ComplianceEngine(rules=[RestrictedListRule(doc)])

    request = compliance_pb2.ComplianceCheckRequest(
        order_id="990e8400-e29b-41d4-a716-446655440099",
        portfolio_id="660e8400-e29b-41d4-a716-446655440099",
        instrument_id=1,
        symbol="CLEAN",
        side="buy",
        qty=10,
        limit_price=100,
        market="US",
    )

    mock_reject = AsyncMock()

    with (
        patch(
            "compliance_service.app.load_check_context",
            AsyncMock(return_value=(portfolio, mandate, "CLEAN")),
        ),
        patch(
            "compliance_service.app.load_active_holds_and_overrides",
            AsyncMock(
                return_value=(
                    [
                        {
                            "entity_type": "portfolio",
                            "entity_id": portfolio.portfolio_id,
                            "reason": "pending litigation",
                            "placed_by": "legal@theeyebeta.com",
                            "placed_at": None,
                        },
                    ],
                    {},
                ),
            ),
        ),
        patch("compliance_service.app.persist_compliance_checks", AsyncMock()),
        patch("compliance_service.app.reject_order_if_blocked", mock_reject),
        patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/db"}, clear=False
        ),
    ):
        result = await check_order_request(engine, request)

    assert result.outcome == ComplianceOutcome.BLOCK
    assert result.approved is False
    assert "legal_hold" in result.failed_rules
    mock_reject.assert_awaited_once()
    assert mock_reject.await_args.kwargs["rule_id"] == "legal_hold"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_compliance_checks_sql() -> None:
    """Direct insert writes one row per rule to compliance_checks."""
    from compliance_service.db import persist_compliance_checks

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    results = [
        RuleResult("restricted_list", ComplianceOutcome.BLOCK, "blocked"),
        RuleResult("wash_sale", ComplianceOutcome.PASS, "ok"),
    ]

    with patch("compliance_service.db.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        await persist_compliance_checks(
            "postgresql://test:test@localhost/db",
            portfolio_id="660e8400-e29b-41d4-a716-446655440099",
            order_id="990e8400-e29b-41d4-a716-446655440099",
            results=results,
        )

    assert mock_conn.execute.await_count == 2
    sql = str(mock_conn.execute.await_args_list[0].args[0])
    assert "INSERT INTO theeyebeta.compliance_checks" in sql
    assert mock_conn.execute.await_args_list[0].args[1][2] == "restricted_list"
    assert mock_conn.execute.await_args_list[0].args[1][3] == "block"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reject_order_updates_status() -> None:
    """Blocked checks move order status to rejected."""
    from compliance_service.db import reject_order_if_blocked

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    order_id = "990e8400-e29b-41d4-a716-446655440099"
    with patch("compliance_service.db.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        await reject_order_if_blocked(
            "postgresql://test:test@localhost/db",
            order_id=order_id,
            outcome=ComplianceOutcome.BLOCK,
            rule_id="restricted_list",
        )

    sql = str(mock_conn.execute.await_args.args[0])
    assert "status = 'rejected'" in sql
    assert mock_conn.execute.await_args.args[1][0] == UUID(order_id)
