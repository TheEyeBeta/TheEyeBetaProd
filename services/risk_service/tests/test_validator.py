"""Unit tests for OrderRiskValidator and persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

# conftest installs zinc_native stub and src path before collection.
from risk_service.metrics import compute_metrics_from_context, insert_risk_metrics
from risk_service.models import OrderProposal, PortfolioRiskContext, RiskOutcome
from risk_service.validator import OrderRiskValidator  # noqa: E402


@pytest.mark.unit
def test_validate_order_allow_within_limits(base_context: PortfolioRiskContext) -> None:
    """Small buy order passes all six checks."""
    validator = OrderRiskValidator()
    order = OrderProposal(
        instrument_id=1,
        side="buy",
        qty=100.0,
        price=100.0,
        sector="technology",
        cluster="tech",
        order_intent="BUY",
    )
    result = validator.validate(base_context, order)
    assert result.outcome == RiskOutcome.ALLOW
    assert result.approved is True
    assert not result.failed_checks


@pytest.mark.unit
def test_validate_order_block_position_size_pct(base_context: PortfolioRiskContext) -> None:
    """Oversized position breaches check 1."""
    validator = OrderRiskValidator()
    order = OrderProposal(
        instrument_id=1,
        side="buy",
        qty=2000.0,
        price=100.0,
        sector="technology",
        cluster="tech",
    )
    result = validator.validate(base_context, order)
    assert result.outcome == RiskOutcome.BLOCK
    assert result.failed_checks[0] == "position_size_pct"


@pytest.mark.unit
def test_validate_order_block_drawdown_circuit_on_buy(
    drawdown_context: PortfolioRiskContext,
) -> None:
    """Drawdown breaker blocks new BUY orders."""
    validator = OrderRiskValidator()
    order = OrderProposal(
        instrument_id=1,
        side="buy",
        qty=10.0,
        price=100.0,
        sector="technology",
        cluster="tech",
        order_intent="BUY",
    )
    result = validator.validate(drawdown_context, order)
    assert result.outcome == RiskOutcome.BLOCK
    assert "drawdown_circuit_breaker" in result.failed_checks


@pytest.mark.unit
def test_validate_order_warn_reduce_under_drawdown(
    drawdown_context: PortfolioRiskContext,
) -> None:
    """REDUCE/EXIT permitted (WARN) when drawdown breaker is active."""
    validator = OrderRiskValidator()
    order = OrderProposal(
        instrument_id=1,
        side="sell",
        qty=10.0,
        price=100.0,
        sector="technology",
        cluster="tech",
        order_intent="REDUCE",
    )
    result = validator.validate(drawdown_context, order)
    assert result.outcome == RiskOutcome.WARN
    assert result.approved is True


@pytest.mark.unit
def test_compute_metrics_uses_cpp_kernels(base_context: PortfolioRiskContext) -> None:
    """Portfolio metrics computation uses zinc_native risk kernels."""
    metrics = compute_metrics_from_context(base_context)
    assert metrics.var_95 >= 0.0
    assert metrics.cvar_95 >= 0.0
    assert 0.0 <= metrics.max_drawdown <= 1.0
    assert metrics.concentration_hhi > 0.0
    assert "cluster_exposures" in metrics.raw


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validate_order_inserts_risk_metrics_row(
    base_context: PortfolioRiskContext,
) -> None:
    """Every ValidateOrder call persists one risk_metrics row."""
    from risk_service.app import validate_order_request
    from zinc_proto import risk_pb2

    ctx = base_context
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    request = risk_pb2.RiskCheckRequest(
        portfolio_id=base_context.portfolio_id,
        instrument_id=1,
        side="buy",
        qty=50.0,
        limit_price=100.0,
        sector="technology",
        cluster="tech",
    )

    with (
        patch(
            "risk_service.app.load_portfolio_context",
            AsyncMock(return_value=ctx),
        ),
        patch("risk_service.app.insert_risk_metrics", AsyncMock()) as mock_insert,
        patch("risk_service.metrics.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)),
        patch.dict(
            "os.environ", {"DATABASE_URL": "postgresql://test:test@localhost/db"}, clear=False
        ),
    ):
        result = await validate_order_request(OrderRiskValidator(), request)

    assert result.outcome == RiskOutcome.ALLOW
    mock_insert.assert_awaited_once()
    inserted = mock_insert.await_args.args[1]
    assert inserted.portfolio_id == base_context.portfolio_id
    assert inserted.var_95 >= 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_portfolio_context_admin_overlay_cannot_loosen_mandate() -> None:
    """admin_risk_limits may not raise a max_* ceiling above the mandate's own value."""
    from risk_service.metrics import load_portfolio_context

    mandate_cursor = AsyncMock()
    mandate_cursor.fetchone = AsyncMock(return_value=({"max_var": 0.03},))

    limits_cursor = AsyncMock()
    limits_cursor.fetchone = AsyncMock(return_value=({"max_var": 0.05},))

    positions_cursor = AsyncMock()
    positions_cursor.fetchall = AsyncMock(return_value=[])

    metrics_cursor = AsyncMock()
    metrics_cursor.fetchone = AsyncMock(return_value=None)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(
        side_effect=[mandate_cursor, limits_cursor, positions_cursor, metrics_cursor],
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("risk_service.metrics.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        ctx = await load_portfolio_context(
            "postgresql://test:test@localhost/db",
            "660e8400-e29b-41d4-a716-446655440001",
        )

    assert ctx.mandate.max_var == 0.03


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_portfolio_context_admin_overlay_can_tighten_mandate() -> None:
    """admin_risk_limits may still lower a max_* ceiling below the mandate's own value."""
    from risk_service.metrics import load_portfolio_context

    mandate_cursor = AsyncMock()
    mandate_cursor.fetchone = AsyncMock(return_value=({"max_var": 0.05},))

    limits_cursor = AsyncMock()
    limits_cursor.fetchone = AsyncMock(return_value=({"max_var": 0.02},))

    positions_cursor = AsyncMock()
    positions_cursor.fetchall = AsyncMock(return_value=[])

    metrics_cursor = AsyncMock()
    metrics_cursor.fetchone = AsyncMock(return_value=None)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(
        side_effect=[mandate_cursor, limits_cursor, positions_cursor, metrics_cursor],
    )
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch("risk_service.metrics.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        ctx = await load_portfolio_context(
            "postgresql://test:test@localhost/db",
            "660e8400-e29b-41d4-a716-446655440001",
        )

    assert ctx.mandate.max_var == 0.02


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_risk_metrics_sql(base_context: PortfolioRiskContext) -> None:
    """Direct insert writes to theeyebeta.risk_metrics."""
    from risk_service.models import ComputedPortfolioMetrics

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=None)

    metrics = ComputedPortfolioMetrics(
        portfolio_id=base_context.portfolio_id,
        var_95=0.02,
        cvar_95=0.03,
        max_drawdown=0.08,
        gross_exposure=80_000.0,
        net_exposure=80_000.0,
        beta_spy=1.0,
        concentration_hhi=0.18,
        raw={"cluster_exposures": {"tech": 0.5}},
    )

    with patch("risk_service.metrics.psycopg.AsyncConnection.connect", AsyncMock(return_value=cm)):
        await insert_risk_metrics("postgresql://test:test@localhost/db", metrics)

    sql = str(mock_conn.execute.call_args.args[0])
    assert "INSERT INTO theeyebeta.risk_metrics" in sql
    assert mock_conn.execute.call_args.args[1][0] == UUID(base_context.portfolio_id)
