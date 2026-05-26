"""Re-export observability metrics for service-root imports (P-MO-02)."""

from master_orchestrator.observability import (
    debate_rounds_total,
    observe_trio_duration,
    record_debate_round,
    record_trio_duration,
    record_trio_outcome,
    trio_duration_seconds,
    trios_total,
)

__all__ = [
    "debate_rounds_total",
    "observe_trio_duration",
    "record_debate_round",
    "record_trio_duration",
    "record_trio_outcome",
    "trio_duration_seconds",
    "trios_total",
]
