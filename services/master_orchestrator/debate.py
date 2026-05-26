"""Re-export debate module for service-root imports (P-MO-01)."""

from master_orchestrator.debate import MAX_DEBATE_ROUNDS, DebateRound

__all__ = ["MAX_DEBATE_ROUNDS", "DebateRound"]
