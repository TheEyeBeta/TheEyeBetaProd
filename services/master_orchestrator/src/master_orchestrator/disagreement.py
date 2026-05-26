"""Decision disagreement helpers."""

from __future__ import annotations

from master_orchestrator.models import AgentDecisionView, AgentRunResult, DecisionKind

# Ordinal scale for directional disagreement (>1 step triggers debate).
DECISION_RANK: dict[str, int] = {
    "SELL": -2,
    "EXIT": -2,
    "REDUCE": -1,
    "OBSERVE": 0,
    "HOLD": 0,
    "BUY": 2,
}


def decision_rank(decision: DecisionKind | str) -> int:
    """Map a decision label to its ordinal rank."""
    return DECISION_RANK.get(str(decision).upper(), 0)


def collect_symbol_decisions(results: list[AgentRunResult]) -> dict[str, list[AgentDecisionView]]:
    """Group decisions by instrument symbol across agents."""
    grouped: dict[str, list[AgentDecisionView]] = {}
    for result in results:
        for decision in result.decisions:
            grouped.setdefault(decision.instrument_symbol, []).append(decision)
    return grouped


def decisions_disagree(results: list[AgentRunResult]) -> bool:
    """Return True when any symbol spans more than one decision step."""
    grouped = collect_symbol_decisions(results)
    for views in grouped.values():
        if len(views) < 2:
            continue
        ranks = [decision_rank(v.decision) for v in views]
        if max(ranks) - min(ranks) > 1:
            return True
    return False
