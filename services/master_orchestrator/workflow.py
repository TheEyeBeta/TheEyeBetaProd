"""Re-export workflow module for service-root imports (P-MO-01)."""

from master_orchestrator.workflow import (
    DEFAULT_TRIO,
    MARKET_TRIO_AGENTS,
    MarketTrioWorkflow,
    agents_for_market,
)

__all__ = [
    "DEFAULT_TRIO",
    "MARKET_TRIO_AGENTS",
    "MarketTrioWorkflow",
    "agents_for_market",
]
