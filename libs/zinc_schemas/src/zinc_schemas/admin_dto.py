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
    reports_to: str | None = None
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


class AgentReportSummary(BaseModel):
    """Operator-facing briefing from one agent."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: str
    audience: str
    run_id: UUID | None = None
    report_type: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None


class BriefingsListResponse(BaseModel):
    """``GET /admin/briefings`` payload."""

    model_config = ConfigDict(extra="forbid")

    briefings: list[AgentReportSummary]
    total: int


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


# --- Control-plane APIs (Tauri desktop client) --------------------------------


class OpenBreakerSummary(BaseModel):
    """Open circuit breaker row for ops pulse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    component: str
    opened_at: str | None = None
    reason: str


class CriticalAlertSummary(BaseModel):
    """Critical alert row for ops pulse."""

    model_config = ConfigDict(extra="forbid")

    id: str
    severity: str
    source: str
    message: str
    created_at: str


class WorkerRunSummary(BaseModel):
    """Worker run row for ops pulse."""

    model_config = ConfigDict(extra="forbid")

    worker: str
    status: str
    started_at: str
    ended_at: str | None = None
    records_written: int = 0


class StaleHeartbeatSummary(BaseModel):
    """Stale heartbeat row for ops pulse."""

    model_config = ConfigDict(extra="forbid")

    worker: str
    last_heartbeat: str | None = None
    expected_interval_seconds: int


class PipelineFreshness(BaseModel):
    """Pipeline freshness timestamps."""

    model_config = ConfigDict(extra="forbid")

    last_eod_ingest: str | None = None
    last_intraday_ingest: str | None = None
    last_indicators: str | None = None


class PreliveLastResult(BaseModel):
    """Last prelive check summary embedded in ops pulse."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    run_at: str | None = None
    checks_passed: int = 0
    checks_failed: int = 0


class TimersSummary(BaseModel):
    """Active/inactive systemd timer counts."""

    model_config = ConfigDict(extra="forbid")

    active: int = 0
    inactive: int = 0


class ServicesSummary(BaseModel):
    """Healthy/degraded/down service counts."""

    model_config = ConfigDict(extra="forbid")

    healthy: int = 0
    degraded: int = 0
    down: int = 0


class AuditChainStatusSummary(BaseModel):
    """Latest scheduled audit chain verification."""

    model_config = ConfigDict(extra="forbid")

    last_verified_at: datetime | None = None
    valid: bool | None = None
    entries_checked: int = 0
    error_message: str | None = None


class OpsPulseResponse(BaseModel):
    """``GET /admin/ops/pulse`` payload."""

    model_config = ConfigDict(extra="forbid")

    health: str
    open_breakers: list[OpenBreakerSummary]
    critical_alerts: list[CriticalAlertSummary]
    last_worker_runs: list[WorkerRunSummary]
    stale_heartbeats: list[StaleHeartbeatSummary]
    pipeline_freshness: PipelineFreshness
    pending_orders_count: int
    llm_cost_mtd_usd: float
    prelive_last_result: PreliveLastResult
    timers_summary: TimersSummary
    services_summary: ServicesSummary
    audit_chain_status: AuditChainStatusSummary | None = None


class MasterAdminControlEntry(BaseModel):
    """One backend capability in the MASTER_ADMIN control matrix."""

    model_config = ConfigDict(extra="forbid")

    feature: str
    category: str
    source: list[str]
    frontend_location: str
    viewable: bool
    controllable: bool
    editable: bool
    schedulable: bool
    kill_switch_needed: bool
    confirmation_needed: bool
    role_required: str
    audit_log_required: bool
    api_exists: bool
    available_actions: list[str] = Field(default_factory=list)
    existing_endpoints: list[str] = Field(default_factory=list)
    missing_backend_work: list[str] = Field(default_factory=list)
    dangerous_actions: list[str] = Field(default_factory=list)
    operator_notes: str | None = None
    priority: str


class MasterAdminControlMatrixResponse(BaseModel):
    """``GET /admin/master-admin/control-matrix`` payload."""

    model_config = ConfigDict(extra="forbid")

    role: str
    authority: str
    generated_at: datetime
    controls: list[MasterAdminControlEntry]
    gaps: list[MasterAdminControlEntry]
    dangerous_actions_require: list[str]


class WorkerRegistryEntry(BaseModel):
    """One worker in the registry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    alias: str | None = None
    worker_class: str
    state: str
    last_heartbeat: datetime | None = None
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    next_scheduled_fire: datetime | None = None
    circuit_breaker_state: str | None = None


class WorkersListResponse(BaseModel):
    """``GET /admin/workers`` payload."""

    model_config = ConfigDict(extra="forbid")

    workers: list[WorkerRegistryEntry]
    total: int


class WorkerRunHistoryEntry(BaseModel):
    """Paginated worker run history row."""

    model_config = ConfigDict(extra="forbid")

    run_id: int
    worker_name: str
    trade_date: date
    run_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    records_written: int | None = None
    error_message: str | None = None


class WorkerRunsResponse(BaseModel):
    """``GET /admin/workers/runs`` payload."""

    model_config = ConfigDict(extra="forbid")

    runs: list[WorkerRunHistoryEntry]
    limit: int
    offset: int
    total: int


class WorkerRunRequest(BaseModel):
    """``POST /admin/workers/{name}/run`` body."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    force: bool = False
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=2000)


class WorkerRunResponse(BaseModel):
    """Worker manual run trigger result."""

    model_config = ConfigDict(extra="forbid")

    worker_name: str
    triggered_at: datetime
    run_id: int | None = None
    exit_code: int | None = None
    status: str
    stdout_tail: str | None = None
    stderr_tail: str | None = None


class TraskFailureSummary(BaseModel):
    """Recent failure for a Trask component."""

    model_config = ConfigDict(extra="forbid")

    component_id: str
    worker_name: str | None = None
    status: str
    started_at: datetime
    error_message: str | None = None


class TraskBreakerDetail(BaseModel):
    """Open breaker with reset eligibility."""

    model_config = ConfigDict(extra="forbid")

    id: int
    component_id: str
    state: str
    failure_count: int
    opened_at: datetime | None = None
    reset_eligible: bool
    recovery_timeout_seconds: int


class TraskDashboardResponse(BaseModel):
    """``GET /admin/trask/dashboard`` payload."""

    model_config = ConfigDict(extra="forbid")

    components_total: int
    components_healthy: int
    components_degraded: int
    components_failed: int
    open_breakers: list[TraskBreakerDetail]
    degraded_components: list[str]
    recent_failures: list[TraskFailureSummary]


class BreakerResetRequest(BaseModel):
    """``POST /admin/trask/breakers/{id}/reset`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    consequences_acknowledged: bool = False
    override: bool = True


class BreakerResetResponse(BaseModel):
    """Breaker after reset."""

    model_config = ConfigDict(extra="forbid")

    id: int
    component_id: str
    state: str
    reset_at: datetime
    reset_by: str


class AlertEntry(BaseModel):
    """One audit alert."""

    model_config = ConfigDict(extra="forbid")

    id: int
    severity: str
    source: str
    message: str
    title: str
    created_at: datetime
    ack_state: str
    acked_by: str | None = None
    acked_at: datetime | None = None
    gap_id: int | None = None
    run_id: int | None = None


class AlertsListResponse(BaseModel):
    """``GET /admin/alerts`` payload."""

    model_config = ConfigDict(extra="forbid")

    alerts: list[AlertEntry]
    limit: int
    offset: int
    total: int


class AlertAckRequest(BaseModel):
    """``POST /admin/alerts/{id}/ack`` body."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class AlertAckResponse(BaseModel):
    """Alert after acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    id: int
    ack_state: str
    acked_by: str
    acked_at: datetime


class PreliveCheckItem(BaseModel):
    """One prelive check result."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    detail: str
    value: Any | None = None


class PreliveResponse(BaseModel):
    """``GET /admin/prelive`` payload."""

    model_config = ConfigDict(extra="forbid")

    overall: str
    run_at: datetime | None = None
    is_stale: bool = False
    checks: list[PreliveCheckItem]


class LiveApprovalRequest(BaseModel):
    """``POST /admin/trading/live-approval`` body."""

    model_config = ConfigDict(extra="forbid")

    enable: bool
    reason: str = Field(min_length=1, max_length=2000)
    consequences_acknowledged: bool
    confirmation_token: str = Field(min_length=1, max_length=128)


class LiveApprovalResponse(BaseModel):
    """Live trading approval state after update."""

    model_config = ConfigDict(extra="forbid")

    live_approval: bool
    updated_at: datetime
    updated_by: str
    accounts_updated: int


class EmergencyHaltRequest(BaseModel):
    """``POST /admin/trading/emergency-halt`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    consequences_acknowledged: bool


class EmergencyHaltResponse(BaseModel):
    """Emergency halt acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    halted: bool
    halted_at: datetime
    halted_by: str
    nats_published: bool
    redis_paused: bool


class TimerEntry(BaseModel):
    """One systemd timer unit."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str
    schedule: str | None = None
    last_trigger: datetime | None = None
    next_trigger: datetime | None = None
    status: str


class TimersListResponse(BaseModel):
    """``GET /admin/timers`` payload."""

    model_config = ConfigDict(extra="forbid")

    timers: list[TimerEntry]
    total: int


class TimerTriggerRequest(BaseModel):
    """``POST /admin/timers/{name}/trigger`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class TimerTriggerResponse(BaseModel):
    """Timer manual trigger result."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str
    triggered_at: datetime
    triggered_by: str
    exit_code: int


class AdminEventEnvelope(BaseModel):
    """Normalized WebSocket event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    type: str
    ts: str
    severity: str
    source: str
    actor: str
    correlation_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
