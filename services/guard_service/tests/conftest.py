"""pytest fixtures for guard-service."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from zinc_schemas.constitution import AgentConstitution, load_constitution

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_REPO = Path(__file__).resolve().parents[3]
_AGENTS = _REPO / "agents"


@pytest.fixture
def macro_constitution() -> AgentConstitution:
    """macro-lead constitution from repo agents/."""
    return load_constitution(_AGENTS / "markets" / "macro-lead.agent.md")


@pytest.fixture
def guard(macro_constitution: AgentConstitution) -> object:
    """ConstitutionGuard with macro-lead only."""
    from guard_service.validator import ConstitutionGuard

    return ConstitutionGuard({"macro-lead": macro_constitution})


@pytest.fixture
def snapshot_us_aapl() -> dict:
    """Minimal packaged snapshot for evidence/mandate checks."""
    return {
        "schema_version": 1,
        "market": "US",
        "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
        "as_of": "2025-01-15T23:59:59+00:00",
        "universe": [{"symbol": "AAPL", "instrument_id": 1}],
        "prices": {
            "AAPL": {
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "adj_close": 105.0,
                "volume": 1_000_000,
            },
        },
        "technicals": {
            "AAPL": {"rsi14": 55.0, "atr14": 1.5},
        },
        "macro": {"us.dgs10": 4.25},
        "news_summary": [],
    }
