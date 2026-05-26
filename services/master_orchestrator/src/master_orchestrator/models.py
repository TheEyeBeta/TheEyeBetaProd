"""Shared Pydantic models for master orchestrator."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DecisionKind = Literal["BUY", "SELL", "HOLD", "REDUCE", "EXIT", "OBSERVE"]
Side = Literal["buy", "sell"]


class AgentDecisionView(BaseModel):
    """One instrument decision from an executor agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    run_id: str
    decision_id: str | None = None
    instrument_symbol: str
    instrument_id: int | None = None
    decision: DecisionKind
    confidence: float = Field(ge=0, le=1)
    horizon_days: int = Field(ge=5, le=30)
    rationale: str
    key_drivers: list[str] = Field(default_factory=list)


class AgentRunResult(BaseModel):
    """Full response from one agent_runtime run."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    run_id: str
    snapshot_id: str
    market_stance: str
    regime_call: str
    decisions: list[AgentDecisionView]


class DebateEntry(BaseModel):
    """One rebuttal turn in the debate transcript."""

    model_config = ConfigDict(extra="forbid")

    round_num: int
    agent_id: str
    run_id: str
    peer_agent_ids: list[str]
    decisions: list[AgentDecisionView]


class DebateTranscript(BaseModel):
    """Bounded debate output."""

    model_config = ConfigDict(extra="forbid")

    rounds: list[DebateEntry] = Field(default_factory=list)
    final_results: list[AgentRunResult] = Field(default_factory=list)


class TradeTicket(BaseModel):
    """Final synthesized order intent."""

    model_config = ConfigDict(extra="forbid")

    market: str
    instrument_id: int
    side: Side
    qty: float = Field(gt=0)
    horizon_days: int = Field(ge=5, le=30)
    rationale_summary: str = Field(max_length=2000)
    decision_id: UUID | None = None


class PackagedSnapshotEvent(BaseModel):
    """NATS payload from snapshot-packager."""

    model_config = ConfigDict(extra="forbid")

    market: str
    date: str
    snapshot_id: str
    blob_uri: str = ""
    schema_version: int = 1


class WorkflowResult(BaseModel):
    """Outcome of a market-trio workflow."""

    model_config = ConfigDict(extra="forbid")

    market: str
    snapshot_id: str
    trade_date: str | None = None
    debated: bool
    order_id: str | None = None
    skipped: bool = False
    outcome: Literal["consensus", "debate", "no-decision", "skipped"] = "consensus"
    ticket: TradeTicket | None = None
    transcript: DebateTranscript | None = None
    agent_results: list[AgentRunResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
