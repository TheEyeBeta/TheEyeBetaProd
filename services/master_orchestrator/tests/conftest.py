"""pytest fixtures for master-orchestrator."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# zinc_test registers itself via the pytest11 entry-point — no explicit
# pytest_plugins declaration needed (double-registration breaks pluggy).

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from master_orchestrator.models import AgentDecisionView, AgentRunResult, TradeTicket  # noqa: E402
from master_orchestrator.settings import Settings  # noqa: E402

SNAPSHOT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
PORTFOLIO_ID = UUID("660e8400-e29b-41d4-a716-446655440001")
TRADE_DATE = "2025-01-15"

_MO_SQL = Path(__file__).resolve().parent / "sql"


@pytest.fixture(scope="session")
def _mo_seed(alembic_upgraded: str) -> None:
    """Seed master-orchestrator trading data on top of the shared alembic fixture."""
    from zinc_test._infra import _normalize_psycopg_dsn, _run_sql_file  # noqa: PLC0415

    _run_sql_file(_normalize_psycopg_dsn(alembic_upgraded), _MO_SQL / "seed_trading.sql")


@pytest.fixture
def settings() -> Settings:
    """Test settings with deterministic portfolio."""
    return Settings(
        database_url="postgresql://test:test@127.0.0.1:5432/theeyebeta",
        default_portfolio_id=str(PORTFOLIO_ID),
        agent_runtime_url="http://agent-runtime.test:8004",
        llm_virtual_key="",
        default_order_qty=100.0,
    )


def _agent_result(
    agent_id: str,
    *,
    symbol: str = "AAPL",
    decision: str = "HOLD",
    instrument_id: int = 1,
    confidence: float = 0.65,
    rationale: str = "technicals.AAPL.rsi14 at 55.",
) -> AgentRunResult:
    run_id = str(uuid4())
    return AgentRunResult(
        agent_id=agent_id,
        run_id=run_id,
        snapshot_id=str(SNAPSHOT_ID),
        market_stance="neutral",
        regime_call="ranging",
        decisions=[
            AgentDecisionView(
                agent_id=agent_id,
                run_id=run_id,
                decision_id=str(uuid4()),
                instrument_symbol=symbol,
                instrument_id=instrument_id,
                decision=decision,  # type: ignore[arg-type]
                confidence=confidence,
                horizon_days=10,
                rationale=rationale,
                key_drivers=["macro.us.dgs10 stable"],
            ),
        ],
    )


@pytest.fixture
def aligned_trio() -> list[AgentRunResult]:
    """Three agents agree on HOLD."""
    return [
        _agent_result("macro-lead", decision="HOLD"),
        _agent_result("news-sentiment", decision="HOLD"),
        _agent_result("technical-analyst", decision="HOLD"),
    ]


@pytest.fixture
def disagreeing_trio() -> list[AgentRunResult]:
    """macro BUY vs technical SELL triggers debate."""
    return [
        _agent_result("macro-lead", decision="BUY", confidence=0.8),
        _agent_result("news-sentiment", decision="HOLD", confidence=0.6),
        _agent_result("technical-analyst", decision="SELL", confidence=0.75),
    ]


@pytest.fixture
def sample_ticket() -> TradeTicket:
    """Expected synthesized ticket."""
    return TradeTicket(
        market="US",
        instrument_id=1,
        side="buy",
        qty=100.0,
        horizon_days=10,
        rationale_summary="Consensus buy on AAPL after debate.",
    )


@pytest.fixture
def integration_env(
    integration_infra: object,
    _mo_seed: None,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """Apply env vars for one master-orchestrator integration test."""
    from zinc_test import IntegrationInfra  # noqa: PLC0415

    infra: IntegrationInfra = integration_infra  # type: ignore[assignment]

    monkeypatch.setenv("DATABASE_URL", infra.database_url)
    monkeypatch.setenv("NATS_URL", infra.nats_url)
    monkeypatch.setenv("REDIS_URL", infra.redis_url)
    monkeypatch.setenv("DEFAULT_PORTFOLIO_ID", str(PORTFOLIO_ID))
    monkeypatch.setenv("AGENT_RUNTIME_URL", "http://agent-runtime.test:8004")
    monkeypatch.setenv("LITELLM_KEY_MASTER_ORCHESTRATOR", "")
    return infra
