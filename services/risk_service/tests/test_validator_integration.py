"""E2E risk validation against testcontainers Postgres."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from zinc_proto import risk_pb2
from zinc_test._infra import _normalize_psycopg_dsn, _run_sql_file, app_dsn_from_admin

_RISK_SQL = Path(__file__).resolve().parent / "sql"
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PORTFOLIO_ID = "a660e8400-e29b-41d4-a716-446655440099"


@pytest.fixture(scope="session")
def risk_integration_dsn(alembic_upgraded: str) -> str:
    """TimescaleDB container with migrations and risk integration seed."""
    _run_sql_file(alembic_upgraded, _RISK_SQL / "seed_risk_integration.sql")
    return app_dsn_from_admin(alembic_upgraded)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_validate_order_blocks_var_and_writes_risk_metrics(
    risk_integration_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order within size limits but over VaR mandate yields BLOCK and a new risk_metrics row."""
    from risk_service.app import validate_order_request
    from risk_service.validator import OrderRiskValidator

    monkeypatch.setenv("DATABASE_URL", risk_integration_dsn)

    dsn = _normalize_psycopg_dsn(risk_integration_dsn)
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.risk_metrics
             WHERE portfolio_id = %s
            """,
            (UUID(PORTFOLIO_ID),),
        )
        rows_before = int(cur.fetchone()[0])
        cur = conn.execute(
            """
            SELECT id FROM theeyebeta.instruments WHERE symbol = 'AAPL'
            """
        )
        instrument_id = int(cur.fetchone()[0])

    request = risk_pb2.RiskCheckRequest(
        portfolio_id=PORTFOLIO_ID,
        instrument_id=instrument_id,
        side="buy",
        qty=1.0,
        limit_price=100.0,
        order_intent="BUY",
        sector="energy",
        cluster="energy",
    )
    result = await validate_order_request(OrderRiskValidator(), request)

    assert result.outcome.name == "BLOCK"
    assert result.failed_checks == ["portfolio_var_95"]
    assert "portfolio_var_95" in result.reason

    with psycopg.connect(dsn) as conn:
        cur = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.risk_metrics
             WHERE portfolio_id = %s
            """,
            (UUID(PORTFOLIO_ID),),
        )
        rows_after = int(cur.fetchone()[0])
        cur = conn.execute(
            """
            SELECT raw
              FROM theeyebeta.risk_metrics
             WHERE portfolio_id = %s
             ORDER BY ts DESC
             LIMIT 1
            """,
            (UUID(PORTFOLIO_ID),),
        )
        latest_raw = cur.fetchone()[0]

    assert rows_after == rows_before + 1
    if isinstance(latest_raw, str):
        latest_raw = json.loads(latest_raw)
    assert latest_raw["validation"]["outcome"] == "BLOCK"
    assert "portfolio_var_95" in latest_raw["validation"]["failed_checks"]
