"""Pydantic models for agent decision output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["BUY", "SELL", "HOLD", "REDUCE", "EXIT", "OBSERVE"]
Stance = Literal["bullish", "bearish", "neutral"]
Regime = Literal["trending", "ranging", "volatile", "calm"]


class AgentDecision(BaseModel):
    """One instrument-level decision from an agent run."""

    model_config = ConfigDict(extra="forbid")

    instrument_symbol: str
    decision: Decision
    confidence: float = Field(ge=0, le=1)
    horizon_days: int = Field(ge=5, le=30)
    key_drivers: list[str] = Field(max_length=5)
    rationale: str = Field(max_length=1500)


class AgentOutput(BaseModel):
    """Top-level JSON output contract for technical-analyst."""

    model_config = ConfigDict(extra="forbid")

    market_stance: Stance
    regime_call: Regime
    decisions: list[AgentDecision]


@dataclass
class ParsedRunOutput:
    """Parsed LLM output — trading decisions or a free-form briefing."""

    mode: Literal["trading", "briefing"]
    trading: AgentOutput | None = None
    briefing: dict[str, Any] | None = None
