"""Pydantic models for rnd-agent LLM output and run results."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposalEvidence(BaseModel):
    """Evidence block attached to a research proposal."""

    model_config = ConfigDict(extra="allow")

    snapshot_id: str | None = None
    backtest_run_id: str | None = None
    notes: list[str] = Field(default_factory=list)


class EstimatedImpact(BaseModel):
    """Optional impact estimate for a proposal."""

    model_config = ConfigDict(extra="forbid")

    confidence: float | None = None
    expected_direction: str | None = None
    summary: str | None = None


class ProposalDraft(BaseModel):
    """One proposal emitted by the R&D agent."""

    model_config = ConfigDict(extra="forbid")

    category: str
    target: str
    current_value: dict[str, Any]
    proposed_value: dict[str, Any]
    rationale: str
    evidence: ProposalEvidence | dict[str, Any] = Field(default_factory=dict)
    estimated_impact: EstimatedImpact | None = None
    validation_backtest_id: UUID | None = None


class RndAgentOutput(BaseModel):
    """Parsed LLM JSON for schema version 2."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[ProposalDraft]


class RunResult(BaseModel):
    """Outcome of one ``RNDRunner.run`` invocation."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    proposal_ids: list[UUID]
    violations: list[dict[str, str]]
    guard_outcome: str
    dry_run: bool = False
