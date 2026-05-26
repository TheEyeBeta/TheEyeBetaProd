"""Pydantic response/request models for admin-service HTTP APIs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InstrumentSummary(BaseModel):
    """Minimal instrument fields for order views."""

    model_config = ConfigDict(extra="forbid")

    id: int
    symbol: str
    exchange_code: str | None = None


class OrderSummary(BaseModel):
    """Order row joined to instrument (list/detail shared core)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    client_order_id: str
    portfolio_id: UUID
    instrument: InstrumentSummary
    side: str
    order_type: str
    qty: Decimal
    limit_price: Decimal | None = None
    status: str
    created_at: datetime


class PendingOrdersResponse(BaseModel):
    """``GET /admin/orders/pending`` payload."""

    model_config = ConfigDict(extra="forbid")

    orders: list[OrderSummary]
    total: int


class OrderDetailResponse(OrderSummary):
    """``GET /admin/orders/{id}`` payload."""

    stop_price: Decimal | None = None
    time_in_force: str
    filled_qty: Decimal
    avg_fill_price: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    approved_at: datetime | None = None
    updated_at: datetime


class ApproveOrderRequest(BaseModel):
    """``POST /admin/orders/{id}/approve`` body (optional note)."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class ApproveOrderResponse(BaseModel):
    """Order after approval."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    approved_by: str
    approved_at: datetime


class RejectOrderRequest(BaseModel):
    """``POST /admin/orders/{id}/reject`` body."""

    model_config = ConfigDict(extra="forbid")

    rejection_reason: str = Field(min_length=1, max_length=2000)


class RejectOrderResponse(BaseModel):
    """Order after rejection."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    metadata: dict[str, Any]


class AuditLogEntry(BaseModel):
    """One row from ``audit_log``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditLogPageResponse(BaseModel):
    """``GET /admin/audit/log`` paginated result."""

    model_config = ConfigDict(extra="forbid")

    entries: list[AuditLogEntry]
    limit: int
    next_cursor: int | None = Field(
        default=None,
        description="Pass as ``cursor`` query param to fetch the next page (older rows).",
    )


class AuditVerifyResponse(BaseModel):
    """``GET /admin/audit/verify`` — hash-chain check via audit-service."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    mismatch_at_id: int | None = None
    rows_checked: int = 0
    detail: str | None = None


class AuditCheckpointSummary(BaseModel):
    """WORM checkpoint metadata row."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    checkpoint_id: str
    last_row_id: int
    signing_ts: datetime
    row_count: int
    s3_uri: str
    created_at: datetime


class AuditCheckpointsResponse(BaseModel):
    """``GET /admin/audit/checkpoints`` payload."""

    model_config = ConfigDict(extra="forbid")

    checkpoints: list[AuditCheckpointSummary]


class AgentSummary(BaseModel):
    """Agent registry row + recent-run aggregates."""

    model_config = ConfigDict(extra="forbid")

    id: str
    department: str
    role: str
    model_default: str
    model_fallback: str | None = None
    constitution_path: str
    active: bool
    last_run_at: datetime | None = None
    runs_7d: int = 0
    success_rate_7d: float | None = Field(
        default=None,
        description=(
            "Fraction of runs in the last 7 days with status='succeeded' (None when no runs)."
        ),
    )


class AgentsListResponse(BaseModel):
    """``GET /admin/agents`` payload."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentSummary]


class AgentRunRow(BaseModel):
    """One row from ``agent_runs`` for the runs listing."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: str
    triggered_by: str
    parent_run_id: UUID | None = None
    snapshot_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    total_cost_usd: Decimal | None = None
    error: str | None = None


class AgentRunsResponse(BaseModel):
    """``GET /admin/agents/{id}/runs`` payload."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    runs: list[AgentRunRow]
    limit: int


class AgentMessageDTO(BaseModel):
    """Peer-agent rationale forwarded to agent-runtime."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    instrument_symbol: str
    decision: str
    rationale: str


class RunAgentRequest(BaseModel):
    """``POST /admin/agents/{id}/run`` body — forwarded to agent-runtime."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    kind: str = Field(default="run", pattern="^(run|rebuttal)$")
    agent_messages: list[AgentMessageDTO] = Field(default_factory=list)


class RunAgentResponse(BaseModel):
    """``POST /admin/agents/{id}/run`` proxied response."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    snapshot_id: str
    kind: str = "run"


class AgentConstitutionResponse(BaseModel):
    """``GET /admin/agents/{id}/constitution`` payload."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    constitution_path: str
    content: str


class GuardViolationEntry(BaseModel):
    """One row from ``theeyebeta.guard_violations`` for the admin viewer."""

    model_config = ConfigDict(extra="forbid")

    id: int
    ts: datetime
    run_id: UUID
    agent_id: str
    violation_type: str
    severity: str
    detail: dict[str, Any] = Field(default_factory=dict)
    resolution: str
    resolved: bool
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class GuardViolationsResponse(BaseModel):
    """``GET /admin/guard/violations`` payload."""

    model_config = ConfigDict(extra="forbid")

    violations: list[GuardViolationEntry]
    limit: int
    next_cursor: int | None = Field(
        default=None,
        description="Pass as ``cursor`` query param to fetch the next page (older rows).",
    )


class ResolveGuardViolationRequest(BaseModel):
    """``POST /admin/guard/violations/{id}/resolve`` body."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class ResolveGuardViolationResponse(BaseModel):
    """Guard violation row after resolution."""

    model_config = ConfigDict(extra="forbid")

    id: int
    resolved: bool
    resolved_by: str
    resolved_at: datetime
    resolution_note: str | None = None


class ServiceStatusEntry(BaseModel):
    """One Docker container on the ``theeyebeta-net`` network."""

    model_config = ConfigDict(extra="forbid")

    name: str
    image: str
    state: str
    health: str | None = None
    started_at: datetime | None = None
    uptime_seconds: int | None = None
    container_id: str


class ServiceStatusResponse(BaseModel):
    """``GET /admin/services/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    services: list[ServiceStatusEntry]
    network: str


class RestartServiceRequest(BaseModel):
    """``POST /admin/services/{name}/restart`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)
    timeout_seconds: int = Field(default=10, ge=1, le=120)


class RestartServiceResponse(BaseModel):
    """Result of a Docker container restart."""

    model_config = ConfigDict(extra="forbid")

    name: str
    container_id: str
    restarted: bool
    state: str


class BacktestRunSummary(BaseModel):
    """One row from ``theeyebeta.backtest_runs`` for the listing."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    strategy_id: str
    start_date: date
    end_date: date
    universe: str
    git_sha: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str
    result_blob_uri: str | None = None


class BacktestListResponse(BaseModel):
    """``GET /admin/backtest`` payload."""

    model_config = ConfigDict(extra="forbid")

    runs: list[BacktestRunSummary]
    limit: int


class StartBacktestRequest(BaseModel):
    """``POST /admin/backtest`` body — forwarded to backtest-engine."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1)
    start_date: date
    end_date: date
    universe: str | None = None
    walk_forward: bool | None = None
    mode: str | None = Field(default=None, pattern="^(replay|redecision)$")
    config: dict[str, Any] = Field(default_factory=dict)


class StartBacktestResponse(BaseModel):
    """Proxied response from backtest-engine ``POST /backtest/run``."""

    model_config = ConfigDict(extra="allow")

    backtest_run_id: UUID
    status: str


class BacktestResultsResponse(BaseModel):
    """Proxied response from backtest-engine ``GET /backtest/{id}/results``."""

    model_config = ConfigDict(extra="allow")

    backtest_run_id: UUID
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    result_blob_uri: str | None = None


class DailyCostEntry(BaseModel):
    """One day of aggregated LLM + vendor API costs."""

    model_config = ConfigDict(extra="forbid")

    date: date
    model_cost_usd: Decimal
    api_cost_usd: Decimal
    total_cost_usd: Decimal


class DailyCostsResponse(BaseModel):
    """``GET /admin/costs/daily`` payload."""

    model_config = ConfigDict(extra="forbid")

    days: int
    start_date: date
    end_date: date
    entries: list[DailyCostEntry]
    total_cost_usd: Decimal


class AgentCostEntry(BaseModel):
    """One agent's cost rollup for a calendar month."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    runs: int
    model_runs: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class CostsByAgentResponse(BaseModel):
    """``GET /admin/costs/by-agent`` payload."""

    model_config = ConfigDict(extra="forbid")

    month: str
    start_date: date
    end_date: date
    agents: list[AgentCostEntry]
    total_cost_usd: Decimal


class SqlQueryRequest(BaseModel):
    """``POST /admin/sql/query`` body — read-only SELECT."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=20_000)
    parameters: list[Any] = Field(default_factory=list, max_length=64)


class SqlQueryResponse(BaseModel):
    """``POST /admin/sql/query`` payload."""

    model_config = ConfigDict(extra="forbid")

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False
    elapsed_ms: int


class SqlExecuteRequest(BaseModel):
    """``POST /admin/sql/execute`` body — write SQL.

    Confirmation is enforced via the ``X-Confirm`` and ``X-Idempotency-Key``
    headers; this body intentionally only carries the statement and bind
    parameters so the audit log captures everything that ran.
    """

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=20_000)
    parameters: list[Any] = Field(default_factory=list, max_length=64)


class SqlExecuteResponse(BaseModel):
    """``POST /admin/sql/execute`` payload."""

    model_config = ConfigDict(extra="forbid")

    command_tag: str
    rows_affected: int
    elapsed_ms: int
    idempotency_key: str


class ProposalSummary(BaseModel):
    """One row from ``theeyebeta.proposals`` for the listing."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    proposed_by: str
    run_id: UUID | None = None
    category: str
    target: str
    rationale: str
    status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    validation_backtest_id: UUID | None = None
    created_at: datetime


class ProposalsListResponse(BaseModel):
    """``GET /admin/proposals`` payload."""

    model_config = ConfigDict(extra="forbid")

    proposals: list[ProposalSummary]
    limit: int
    next_cursor: datetime | None = Field(
        default=None,
        description=(
            "Pass as ``cursor`` query param (older ``created_at``) to fetch the next page."
        ),
    )


class ProposalDetail(ProposalSummary):
    """``GET /admin/proposals/{id}`` payload (full row)."""

    current_value: dict[str, Any] = Field(default_factory=dict)
    proposed_value: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    estimated_impact: dict[str, Any] | None = None
    applied_at: datetime | None = None
    applied_commit_sha: str | None = None


class ApproveProposalRequest(BaseModel):
    """``POST /admin/proposals/{id}/approve`` body.

    By default, approval triggers a validation backtest. Operators can pass
    ``skip_backtest=true`` for proposals whose ``target`` is not a strategy.
    """

    model_config = ConfigDict(extra="forbid")

    review_notes: str | None = Field(default=None, max_length=2000)
    skip_backtest: bool = False
    strategy_id: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    universe: str | None = Field(default="sp500", max_length=200)
    git_sha: str | None = Field(default=None, max_length=200)


class ApproveProposalResponse(BaseModel):
    """Proposal row after approval."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    reviewed_by: str
    reviewed_at: datetime
    validation_backtest_id: UUID | None = None
    review_notes: str | None = None


class RejectProposalRequest(BaseModel):
    """``POST /admin/proposals/{id}/reject`` body."""

    model_config = ConfigDict(extra="forbid")

    review_notes: str = Field(min_length=1, max_length=2000)


class RejectProposalResponse(BaseModel):
    """Proposal row after rejection."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    reviewed_by: str
    reviewed_at: datetime
    review_notes: str
