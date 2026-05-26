"""pytest fixtures for risk-service."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

# zinc_test registers itself via the pytest11 entry-point — no explicit
# pytest_plugins declaration needed (double-registration breaks pluggy).

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _install_zinc_native_risk_stub() -> None:
    """Provide risk kernels when the C++ extension is not built."""
    if "zinc_native._zinc_risk" in sys.modules:
        return

    def historical_var(samples: np.ndarray, alpha: float) -> float:
        return float(np.quantile(samples, alpha))

    def cvar(samples: np.ndarray, alpha: float) -> float:
        cutoff = np.quantile(samples, alpha)
        tail = samples[samples <= cutoff]
        return float(np.mean(tail)) if tail.size else 0.0

    def max_drawdown(wealth: np.ndarray) -> float:
        if wealth.size == 0:
            return 0.0
        peak = float(wealth[0])
        worst = 0.0
        for value in wealth:
            peak = max(peak, float(value))
            if peak > 0:
                worst = max(worst, (peak - float(value)) / peak)
        return worst

    stub = types.ModuleType("zinc_native.risk")
    stub.historical_var = historical_var  # type: ignore[attr-defined]
    stub.cvar = cvar  # type: ignore[attr-defined]
    stub.max_drawdown = max_drawdown  # type: ignore[attr-defined]
    sys.modules["zinc_native._zinc_risk"] = stub
    sys.modules["zinc_native.risk"] = stub


_install_zinc_native_risk_stub()

from risk_service.models import (  # noqa: E402
    PortfolioMandate,
    PortfolioRiskContext,
    PositionRow,
)

PORTFOLIO_ID = "660e8400-e29b-41d4-a716-446655440001"
INSTRUMENT_A = 1
INSTRUMENT_B = 2


def synthetic_context(
    *,
    nav: float = 1_000_000.0,
    mandate: PortfolioMandate | None = None,
    drawdown_wealth: list[float] | None = None,
) -> PortfolioRiskContext:
    """Build a deterministic portfolio for validator unit tests."""
    m = mandate or PortfolioMandate(
        max_position_pct=0.10,
        max_sector_pct=0.35,
        max_correlation_cluster_pct=0.40,
        max_var=0.05,
        max_drawdown_pct=0.15,
        max_hhi=0.30,
    )
    positions = [
        PositionRow(
            instrument_id=INSTRUMENT_A,
            symbol="AAPL",
            sector="technology",
            cluster="tech",
            qty=500.0,
            market_value=50_000.0,
        ),
        PositionRow(
            instrument_id=INSTRUMENT_B,
            symbol="XOM",
            sector="energy",
            cluster="energy",
            qty=300.0,
            market_value=30_000.0,
        ),
    ]
    wealth = drawdown_wealth or [nav, nav * 0.98, nav * 0.97, nav * 0.96, nav * 0.95]
    return PortfolioRiskContext(
        portfolio_id=PORTFOLIO_ID,
        nav=nav,
        mandate=m,
        positions=positions,
        return_samples=np.array([-0.01, 0.005, -0.008, 0.002, -0.004]),
        wealth_30d=np.array(wealth, dtype=float),
        cluster_exposures={"tech": 50_000.0, "energy": 30_000.0},
        beta_spy=1.0,
    )


@pytest.fixture
def base_context() -> PortfolioRiskContext:
    """Portfolio within all risk limits."""
    return synthetic_context()


@pytest.fixture
def drawdown_context() -> PortfolioRiskContext:
    """Portfolio with 30d drawdown above 15% circuit breaker."""
    nav = 1_000_000.0
    wealth = [nav, nav * 0.90, nav * 0.85, nav * 0.82, nav * 0.80]
    return synthetic_context(nav=nav, drawdown_wealth=wealth)
