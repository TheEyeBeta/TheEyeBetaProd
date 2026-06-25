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
    """``POST /admin/orders/{id}/approve`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
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
    confirm: bool


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


class StartBacktestDangerousRequest(StartBacktestRequest):
    """``POST /admin/backtests`` body with confirmation."""

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


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

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
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


class ControlMatrixEntry(BaseModel):
    """One row in the MASTER_ADMIN control matrix — source of truth for parity."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    category: str
    backend_source: str | None = None
    frontend_location: str | None = None
    api_route: str | None = None
    role_required: str = Field(
        description="operator | MASTER_ADMIN | none | service_jwt",
    )
    viewable: bool
    controllable: bool
    editable: bool = False
    schedulable: bool = False
    kill_switch: bool = False
    dangerous: bool = False
    confirmation_required: bool = False
    audit_required: bool = False
    audit_implemented: bool = False
    backend_gap: str | None = None
    frontend_gap: str | None = None
    backend_only_reason: str | None = None
    cloudflare_dependency: str | None = None
    service_port_dependency: str | None = None
    trusted_host_dependency: bool = False
    health_endpoint: str | None = None
    priority: str = Field(description="Critical | High | Medium | Low")
    notes: str | None = None


class ControlMatrixCategorySummary(BaseModel):
    """Aggregate counts for one matrix category."""

    model_config = ConfigDict(extra="forbid")

    category: str
    total: int
    viewable: int
    controllable: int
    critical_count: int
    gap_count: int


class ControlMatrixResponse(BaseModel):
    """``GET /admin/master-admin/control-matrix`` payload."""

    model_config = ConfigDict(extra="forbid")

    version: str
    generated_at: datetime
    entries: list[ControlMatrixEntry]
    categories: list[ControlMatrixCategorySummary]
    drift_alerts: list[str] = Field(default_factory=list)


# --- Edge Route Registry & Cloudflare status ---


class EdgeDriftStatus(BaseModel):
    """Drift classification for one edge route."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        description="ok | port_mismatch | tunnel_mismatch | host_header_risk | "
        "port_not_listening | health_unhealthy | config_missing | critical | unknown",
    )
    messages: list[str] = Field(default_factory=list)
    action_needed: str | None = None


class EdgeRouteEntry(BaseModel):
    """One registered public edge route with live drift fields."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    environment: str = Field(description="dev | staging | prod | shared")
    expected_internal_host: str
    expected_internal_port: int
    actual_tunnel_target: str | None = None
    expected_service_name: str
    systemd_unit: str | None = None
    health_endpoint: str
    expected_health_status: str = "healthy"
    trusted_host_required: bool = False
    trusted_host_present: bool | None = None
    repo_config_source: str | None = None
    runtime_config_source: str | None = None
    cloudflare_remote_ingress_status: str = Field(
        default="unknown",
        description="synced | drift | unavailable_no_credentials | unknown",
    )
    port_listening: bool | None = None
    health_status: str = Field(default="unknown", description="healthy | unhealthy | unknown")
    drift: EdgeDriftStatus
    last_checked_at: datetime
    owner_module: str
    notes: str | None = None


class EdgeRouteListResponse(BaseModel):
    """``GET /admin/edge/routes`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(description="local | live")
    shared_backend_warning: str | None = None
    routes: list[EdgeRouteEntry]
    last_checked_at: datetime


class EdgeRouteDetailResponse(BaseModel):
    """``GET /admin/edge/routes/{hostname}`` payload."""

    model_config = ConfigDict(extra="forbid")

    route: EdgeRouteEntry


class EdgeDriftReportResponse(BaseModel):
    """``GET /admin/edge/routes/drift`` and alias ``/admin/cloudflare/routes/drift``."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    critical_count: int
    drift_count: int
    routes: list[EdgeRouteEntry]
    alerts: list[str] = Field(default_factory=list)
    last_checked_at: datetime


class EdgePortRegistryEntry(BaseModel):
    """Registered or discovered service port."""

    model_config = ConfigDict(extra="forbid")

    port: int
    host: str = "127.0.0.1"
    service_name: str
    systemd_unit: str | None = None
    expected: bool = True
    listening: bool | None = None
    registered_in_repo: bool = False
    notes: str | None = None


class EdgePortRegistryResponse(BaseModel):
    """``GET /admin/edge/ports`` payload."""

    model_config = ConfigDict(extra="forbid")

    ports: list[EdgePortRegistryEntry]
    unregistered_incident_ports: list[int] = Field(
        default_factory=lambda: [9500],
        description="Ports that indicate Critical drift if used as tunnel targets.",
    )
    last_checked_at: datetime


class EdgeTrustedHostEntry(BaseModel):
    """Trusted Host header allowlist row for one public hostname."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    required: bool
    present_in_runtime: bool | None = None
    present_in_repo_example: bool | None = None
    drift: bool = False
    source_runtime: str | None = None
    source_repo_example: str | None = None


class EdgeTrustedHostsResponse(BaseModel):
    """``GET /admin/edge/trusted-hosts`` payload."""

    model_config = ConfigDict(extra="forbid")

    runtime_hosts: list[str] = Field(
        description="Hostnames only — never raw .env values.",
    )
    repo_example_hosts: list[str]
    entries: list[EdgeTrustedHostEntry]
    last_checked_at: datetime


class CloudflareTunnelInfo(BaseModel):
    """Tunnel summary (no credentials)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    tunnel_id: str | None = None
    configured: bool = False
    health: str = Field(default="unknown", description="healthy | degraded | unknown")
    config_source: str | None = None
    ingress_hostnames: list[str] = Field(default_factory=list)


class CloudflareDnsRoute(BaseModel):
    """DNS / tunnel ingress route (redacted)."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    origin_target: str | None = None
    repo_target: str | None = None
    host_target: str | None = None
    remote_target: str | None = None
    drift: bool = False


class CloudflareAccessStatus(BaseModel):
    """Cloudflare Access policy presence (no secrets)."""

    model_config = ConfigDict(extra="forbid")

    enabled: str = Field(default="unknown", description="yes | no | unknown")
    apps_count: int | None = None
    detail: str | None = None


class CloudflareWafStatus(BaseModel):
    """WAF / rate-limiting summary."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="unknown")
    recent_events_count: int = 0
    detail: str | None = None


class CloudflareWorkerGatewayStatus(BaseModel):
    """Optional Worker / API gateway layer."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="unknown", description="active | none | unknown")
    detail: str | None = None


class CloudflareStatusResponse(BaseModel):
    """``GET /admin/cloudflare/status`` payload — never includes secrets."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(description="local | live")
    cloudflare_configured: bool
    tunnel_configured: bool
    tunnel_health: str = Field(description="healthy | degraded | unknown")
    public_hostnames: list[str] = Field(default_factory=list)
    origin_targets: list[str] = Field(default_factory=list)
    access: CloudflareAccessStatus
    waf: CloudflareWafStatus
    worker_gateway: CloudflareWorkerGatewayStatus
    dns_route_status: str = Field(default="unknown")
    credentials_present: bool
    config_sources: list[str] = Field(default_factory=list)
    last_checked_at: datetime
    missing_setup_steps: list[str] = Field(default_factory=list)
    dummy_mode_warning: str | None = None


class CloudflareTunnelsResponse(BaseModel):
    """``GET /admin/cloudflare/tunnels`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    tunnels: list[CloudflareTunnelInfo]
    last_checked_at: datetime


class CloudflareDnsRoutesResponse(BaseModel):
    """``GET /admin/cloudflare/dns/routes`` and alias ``/admin/cloudflare/routes``."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    routes: list[CloudflareDnsRoute]
    last_checked_at: datetime


class CloudflareAccessAppsResponse(BaseModel):
    """``GET /admin/cloudflare/access/apps`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    enabled: str
    apps: list[str] = Field(default_factory=list, description="App hostnames only.")
    last_checked_at: datetime


class CloudflareWafEventsResponse(BaseModel):
    """``GET /admin/cloudflare/waf/events`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    events: list[dict[str, str]] = Field(
        default_factory=list,
        description="Sanitized event summaries — no raw payloads.",
    )
    last_checked_at: datetime


class CloudflareTestRequest(BaseModel):
    """``POST /admin/cloudflare/test`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class CloudflareTestResponse(BaseModel):
    """``POST /admin/cloudflare/test`` result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    mode: str
    drift_report: EdgeDriftReportResponse
    cloudflare_status: CloudflareStatusResponse


class EdgeRoutesCheckRequest(BaseModel):
    """``POST /admin/edge/routes/check`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class EdgeRoutesCheckResponse(BaseModel):
    """``POST /admin/edge/routes/check`` result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    drift_report: EdgeDriftReportResponse
    routes: EdgeRouteListResponse


class AdminUserSummary(BaseModel):
    """Operator account row — never includes password or secrets."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    username: str
    display_name: str | None = None
    email: str | None = None
    active: bool
    mfa_enabled: bool
    roles: list[str]
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    """``GET /admin/users`` JSON payload."""

    model_config = ConfigDict(extra="forbid")

    users: list[AdminUserSummary]


class AdminUserAuditEntry(BaseModel):
    """Sanitized audit row for user detail panel."""

    model_config = ConfigDict(extra="forbid")

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload_summary: dict[str, Any] = Field(default_factory=dict)


class AdminUserDetailResponse(AdminUserSummary):
    """``GET /admin/users/{id}`` payload."""

    audit_history: list[AdminUserAuditEntry] = Field(default_factory=list)


class AdminUserCreateRequest(BaseModel):
    """``POST /admin/users`` body — password never returned."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=256)
    roles: list[str] = Field(default_factory=lambda: ["operator"])
    reason: str = Field(min_length=1, max_length=2000)


class AdminUserPatchRequest(BaseModel):
    """``PATCH /admin/users/{id}`` body."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=256)
    email: str | None = Field(default=None, max_length=256)


class AdminUserRoleListResponse(BaseModel):
    """``GET /admin/users/{id}/roles`` payload."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    roles: list[str]


class AdminUserRolesChangeResponse(BaseModel):
    """Role grant/revoke result."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    roles: list[str]


class AdminUserSessionEntry(BaseModel):
    """One refresh-token session — no token values exposed."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    user_agent: str | None = None
    ip_address: str | None = None
    created_at: datetime
    last_seen_at: datetime
    active: bool
    revoked_at: datetime | None = None


class AdminUserSessionListResponse(BaseModel):
    """``GET /admin/users/{id}/sessions`` payload."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    sessions: list[AdminUserSessionEntry]


class WorkerControlGap(BaseModel):
    """Control action not safely wired end-to-end."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class WorkerRunEntry(BaseModel):
    """One row from ``public.audit_worker_runs``."""

    model_config = ConfigDict(extra="forbid")

    run_id: int
    worker_name: str
    worker_type: str
    trade_date: date
    run_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    records_written: int | None = None
    records_expected: int | None = None
    error_message: str | None = None
    error_class: str | None = None


class WorkerRegistryEntry(BaseModel):
    """Worker registry row for Terminal operators."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    audit_worker_name: str | None = None
    audit_worker_names: list[str] = Field(default_factory=list)
    systemd_service: str | None = None
    timer_unit: str | None = None
    schedule: str
    priority: str = "Medium"
    health: str
    paused: bool = False
    enabled: bool = True
    last_run: WorkerRunEntry | None = None
    next_scheduled_run: str | None = None
    heartbeat_at: datetime | None = None
    heartbeat_status: str | None = None
    recent_failures: list[WorkerRunEntry] = Field(default_factory=list)
    control_gaps: list[WorkerControlGap] = Field(default_factory=list)
    supports_run: bool = True
    supports_stop: bool = False
    supports_pause: bool = False
    supports_resume: bool = False
    supports_retry: bool = True
    supports_config: bool = True
    source_path: str | None = None


class WorkerListResponse(BaseModel):
    """``GET /admin/workers`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    audit_tables_available: bool
    workers: list[WorkerRegistryEntry]
    checked_at: datetime


class WorkerDetailResponse(WorkerRegistryEntry):
    """``GET /admin/workers/{name}`` payload."""

    runs: list[WorkerRunEntry] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    timer_mapping: dict[str, Any] = Field(default_factory=dict)


class WorkerRunListResponse(BaseModel):
    """``GET /admin/workers/{name}/runs`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    runs: list[WorkerRunEntry]


class WorkerConfigResponse(BaseModel):
    """``GET /admin/workers/{name}/config`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    editable: bool = True


class WorkerConfigPatchRequest(BaseModel):
    """``PATCH /admin/workers/{name}/config`` — dangerous mutation."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    config: dict[str, Any] = Field(default_factory=dict)


class WorkerLogEntry(BaseModel):
    """Structured log line from audit or journal."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    level: str
    source: str
    message: str
    run_id: int | None = None


class WorkerLogsResponse(BaseModel):
    """``GET /admin/workers/{name}/logs`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    lines: list[WorkerLogEntry]
    journal_available: bool


class WorkerActionResponse(BaseModel):
    """Result of a worker control mutation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action: str
    status: str
    message: str
    audited: bool
    systemd_unit: str | None = None
    reason: str


class TimerRegistryEntry(BaseModel):
    """Systemd timer mapped to a worker."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    worker_key: str
    systemd_timer: str
    systemd_service: str | None = None
    schedule: str
    enabled: bool = True
    next_run: str | None = None
    control_gaps: list[WorkerControlGap] = Field(default_factory=list)
    supports_trigger: bool = True
    supports_enable: bool = True
    supports_disable: bool = True
    supports_schedule_edit: bool = True


class TimerListResponse(BaseModel):
    """``GET /admin/timers`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    timers: list[TimerRegistryEntry]
    checked_at: datetime


class TimerDetailResponse(TimerRegistryEntry):
    """``GET /admin/timers/{name}`` payload."""

    worker: WorkerDetailResponse | None = None


class TimerSchedulePatchRequest(BaseModel):
    """``PATCH /admin/timers/{name}/schedule`` — dangerous mutation."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    schedule: str = Field(min_length=1, max_length=256)


class TimerActionResponse(BaseModel):
    """Result of a timer control mutation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action: str
    status: str
    message: str
    audited: bool
    reason: str


class TimerJournalEntry(BaseModel):
    """Timer journal line."""

    model_config = ConfigDict(extra="forbid")

    ts: datetime
    message: str
    source: str


class TimerJournalResponse(BaseModel):
    """``GET /admin/timers/{name}/journal`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    entries: list[TimerJournalEntry]
    journal_available: bool


class ServiceActionRequest(BaseModel):
    """Body for audited service mutations (restart/start/enable)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class ServiceHistoryEntry(BaseModel):
    """One operator action against an allowlisted service."""

    model_config = ConfigDict(extra="forbid")

    id: int
    service_name: str
    action: str
    actor: str
    reason: str
    status: str
    message: str
    created_at: datetime


class ServiceLogLine(BaseModel):
    """Bounded sanitized journal line."""

    model_config = ConfigDict(extra="forbid")

    line: str
    source: str = "journal"


class ServiceRegistryEntry(BaseModel):
    """Allowlisted systemd service with port ownership."""

    model_config = ConfigDict(extra="forbid")

    name: str
    title: str
    systemd_unit: str
    unit_file: str
    status: str
    health: str
    health_probe: str | None = None
    uptime_seconds: int | None = None
    restart_count: int | None = None
    memory_bytes: int | None = None
    cpu_usage_nsec: int | None = None
    listening_port: int | None = None
    port_listening: bool | None = None
    public_hostnames: list[str] = Field(default_factory=list)
    health_endpoint: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    enabled: bool | None = None
    critical: bool = False
    supports_restart: bool = True
    supports_start: bool = True
    supports_stop: bool = True
    supports_enable: bool = True
    supports_disable: bool = True
    started_at: datetime | None = None
    last_operator_action: ServiceHistoryEntry | None = None
    priority: str = "Medium"


class ServiceListResponse(BaseModel):
    """``GET /admin/services`` payload."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    services: list[ServiceRegistryEntry]
    checked_at: datetime


class ServiceDetailResponse(ServiceRegistryEntry):
    """``GET /admin/services/{name}`` payload."""

    recent_logs: list[ServiceLogLine] = Field(default_factory=list)
    history: list[ServiceHistoryEntry] = Field(default_factory=list)


class ServiceActionResponse(BaseModel):
    """Result of a service control mutation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    action: str
    status: str
    message: str
    audited: bool
    systemd_unit: str
    reason: str


class ServiceLogsResponse(BaseModel):
    """``GET /admin/services/{name}/logs`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    lines: list[ServiceLogLine]
    bounded: bool = True
    journal_available: bool


class ServiceHistoryResponse(BaseModel):
    """``GET /admin/services/{name}/history`` payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    entries: list[ServiceHistoryEntry]


class ServicePortEntry(BaseModel):
    """Port ownership row tying listeners to services and hostnames."""

    model_config = ConfigDict(extra="forbid")

    port: int
    host: str
    service_name: str
    systemd_unit: str | None = None
    public_hostnames: list[str] = Field(default_factory=list)
    health_endpoint: str | None = None
    expected: bool
    listening: bool | None = None
    notes: str | None = None


class ServicePortRegistryResponse(BaseModel):
    """``GET /admin/services/ports`` payload."""

    model_config = ConfigDict(extra="forbid")

    ports: list[ServicePortEntry]
    unregistered_incident_ports: list[int]
    checked_at: datetime


class TradingComponentStatus(BaseModel):
    """Readiness for one trading dependency."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    message: str | None = None
    reachable: bool | None = None


class TradingApprovalTokenState(BaseModel):
    """Outstanding live-approval tokens."""

    model_config = ConfigDict(extra="forbid")

    pending_tokens: int = 0
    last_issued_at: datetime | None = None
    next_expires_at: datetime | None = None


class TradingStatusResponse(BaseModel):
    """``GET /admin/trading/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    live_trading_enabled: bool
    broker_mode: str
    emergency_halt: bool
    approval_token_state: TradingApprovalTokenState
    last_halt_reason: str | None = None
    last_halt_at: datetime | None = None
    last_resume_reason: str | None = None
    last_resume_at: datetime | None = None
    last_operator: str | None = None
    broker: TradingComponentStatus
    oms: TradingComponentStatus
    risk: TradingComponentStatus
    compliance: TradingComponentStatus
    edge_api: TradingComponentStatus
    checked_at: datetime


class LiveApprovalTokenResponse(BaseModel):
    """``POST /admin/trading/live-approval-token`` — plaintext shown once."""

    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: datetime
    message: str


class LiveApprovalRequest(BaseModel):
    """``POST /admin/trading/live-approval`` body."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=256)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class TradingEventEntry(BaseModel):
    """One trading control plane event."""

    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    actor: str
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TradingEventListResponse(BaseModel):
    """``GET /admin/trading/events`` payload."""

    model_config = ConfigDict(extra="forbid")

    events: list[TradingEventEntry]


class TradingGateHistoryResponse(BaseModel):
    """``GET /admin/trading/gate-history`` payload."""

    model_config = ConfigDict(extra="forbid")

    entries: list[TradingEventEntry]


class RiskControlGapEntry(BaseModel):
    """Advisory gap for a risky control action."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class RiskStatusResponse(BaseModel):
    """``GET /admin/risk/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    service_health: str
    service_reachable: bool | None = None
    metrics_stale: bool
    last_compute_at: datetime | None = None
    last_compute_by: str | None = None
    limit_version: int
    limits_source_mandate: dict[str, Any] = Field(default_factory=dict)
    limits_overlay: dict[str, Any] = Field(default_factory=dict)
    portfolio_exposure: dict[str, float] = Field(default_factory=dict)
    var_95: float | None = None
    cvar_95: float | None = None
    concentration_hhi: float | None = None
    correlation_clusters: dict[str, float] = Field(default_factory=dict)
    active_breach_count: int = 0
    active_override_count: int = 0
    trading_locked: bool = False
    emergency_halt: bool = False
    live_trading_enabled: bool = False
    control_gaps: list[RiskControlGapEntry] = Field(default_factory=list)
    checked_at: datetime


class RiskMetricsResponse(BaseModel):
    """``GET /admin/risk/metrics`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    metrics: dict[str, Any] | None = None
    stale: bool
    checked_at: datetime


class RiskLimitsResponse(BaseModel):
    """``GET /admin/risk/limits`` payload."""

    model_config = ConfigDict(extra="forbid")

    version: int
    limits: dict[str, Any]
    mandate_limits: dict[str, Any]
    editable: bool = True
    control_gaps: list[RiskControlGapEntry] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by: str | None = None


class RiskLimitPatchRequest(BaseModel):
    """``PATCH /admin/risk/limits`` body."""

    model_config = ConfigDict(extra="forbid")

    limits: dict[str, float]
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class RiskBreachEntry(BaseModel):
    """One active limit breach."""

    model_config = ConfigDict(extra="forbid")

    check: str
    limit: float
    actual: float
    severity: str


class RiskBreachListResponse(BaseModel):
    """``GET /admin/risk/breaches`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    breaches: list[RiskBreachEntry]


class RiskFailureEntry(BaseModel):
    """Historical validation failure from risk metrics."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    ts: datetime
    failed_checks: list[str] = Field(default_factory=list)
    outcome: str


class RiskFailureListResponse(BaseModel):
    """``GET /admin/risk/failures`` payload."""

    model_config = ConfigDict(extra="forbid")

    failures: list[RiskFailureEntry]


class RiskEventEntry(BaseModel):
    """One risk control plane event."""

    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    actor: str
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RiskHistoryResponse(BaseModel):
    """``GET /admin/risk/history`` payload."""

    model_config = ConfigDict(extra="forbid")

    entries: list[RiskEventEntry]


class RiskComputeResponse(BaseModel):
    """``POST /admin/risk/compute`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    mode: str
    metrics: dict[str, Any] | None = None
    audited: bool = True
    reason: str


class RiskOverrideRequest(BaseModel):
    """``POST /admin/risk/override`` body."""

    model_config = ConfigDict(extra="forbid")

    check_name: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    portfolio_id: str | None = None
    expires_in_minutes: int | None = Field(default=None, ge=1, le=1440)


class RiskOverrideResponse(BaseModel):
    """``POST /admin/risk/override`` response."""

    model_config = ConfigDict(extra="forbid")

    id: int
    portfolio_id: str | None = None
    check_name: str
    reason: str
    expires_at: datetime | None = None
    audited: bool = True


class ComplianceControlGapEntry(BaseModel):
    """Advisory gap for a compliance control action."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class ComplianceRuleEntry(BaseModel):
    """Catalog entry for a built-in compliance rule."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    title: str
    group: str


class ComplianceStatusResponse(BaseModel):
    """``GET /admin/compliance/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    service_health: str
    service_reachable: bool | None = None
    rule_version: int
    rules_overlay: dict[str, Any] = Field(default_factory=dict)
    mandate_rules: dict[str, Any] = Field(default_factory=dict)
    rule_catalog: list[ComplianceRuleEntry] = Field(default_factory=list)
    restricted_list: dict[str, Any] = Field(default_factory=dict)
    recent_failed_count: int = 0
    active_override_count: int = 0
    active_exception_count: int = 0
    active_legal_hold_count: int = 0
    unresolved_guard_violations: int = 0
    last_recheck_at: datetime | None = None
    last_recheck_by: str | None = None
    control_gaps: list[ComplianceControlGapEntry] = Field(default_factory=list)
    checked_at: datetime


class ComplianceCheckEntry(BaseModel):
    """One persisted compliance check row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    order_id: str | None = None
    portfolio_id: str | None = None
    rule_id: str
    outcome: str
    detail: str | None = None
    checked_at: datetime


class ComplianceCheckListResponse(BaseModel):
    """``GET /admin/compliance/checks`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str | None = None
    checks: list[ComplianceCheckEntry]


class ComplianceRecheckRequest(BaseModel):
    """``POST /admin/compliance/checks/recheck`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    portfolio_id: str | None = None
    instrument_id: int | None = Field(default=None, ge=1)
    side: str = Field(default="buy", min_length=1, max_length=16)
    qty: float = Field(default=1.0, gt=0)
    limit_price: float = Field(default=100.0, gt=0)


class ComplianceRecheckResponse(BaseModel):
    """``POST /admin/compliance/checks/recheck`` response."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    instrument_id: int
    mode: str
    outcome: str
    approved: bool | None = None
    failed_checks: list[str] = Field(default_factory=list)
    recent_checks: list[ComplianceCheckEntry] = Field(default_factory=list)
    audited: bool = True
    reason: str


class ComplianceRulesResponse(BaseModel):
    """``GET /admin/compliance/rules`` payload."""

    model_config = ConfigDict(extra="forbid")

    version: int
    rules: dict[str, Any]
    mandate_rules: dict[str, Any]
    editable: bool = True
    control_gaps: list[ComplianceControlGapEntry] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by: str | None = None


class ComplianceRulesPatchRequest(BaseModel):
    """``PATCH /admin/compliance/rules`` body."""

    model_config = ConfigDict(extra="forbid")

    rules: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class ComplianceOverrideRequest(BaseModel):
    """``POST /admin/compliance/override`` body."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    portfolio_id: str | None = None
    expires_in_minutes: int | None = Field(default=None, ge=1, le=1440)


class ComplianceOverrideResponse(BaseModel):
    """``POST /admin/compliance/override`` response."""

    model_config = ConfigDict(extra="forbid")

    id: int
    portfolio_id: str | None = None
    rule_id: str
    reason: str
    expires_at: datetime | None = None
    audited: bool = True


class ComplianceExceptionEntry(BaseModel):
    """One active compliance exception."""

    model_config = ConfigDict(extra="forbid")

    id: int
    portfolio_id: str | None = None
    rule_id: str
    reason: str
    actor: str
    expires_at: datetime | None = None
    created_at: datetime


class ComplianceExceptionListResponse(BaseModel):
    """``GET /admin/compliance/exceptions`` payload."""

    model_config = ConfigDict(extra="forbid")

    exceptions: list[ComplianceExceptionEntry]


class ComplianceExceptionCreateRequest(BaseModel):
    """``POST /admin/compliance/exceptions`` body."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    portfolio_id: str | None = None
    expires_in_minutes: int | None = Field(default=None, ge=1, le=1440)


class ComplianceLegalHoldRequest(BaseModel):
    """``POST /admin/compliance/legal-hold`` body."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(apply|release)$")
    entity_type: str = Field(pattern="^(portfolio|account|instrument)$")
    entity_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class ComplianceLegalHoldResponse(BaseModel):
    """``POST /admin/compliance/legal-hold`` response."""

    model_config = ConfigDict(extra="forbid")

    id: int
    entity_type: str
    entity_id: str
    active: bool
    reason: str
    placed_by: str
    placed_at: datetime
    released_by: str | None = None
    released_at: datetime | None = None
    audited: bool = True


class ComplianceEventEntry(BaseModel):
    """One compliance control plane event."""

    model_config = ConfigDict(extra="forbid")

    id: int
    event_type: str
    actor: str
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ComplianceHistoryResponse(BaseModel):
    """``GET /admin/compliance/history`` payload."""

    model_config = ConfigDict(extra="forbid")

    entries: list[ComplianceEventEntry]


class OrderListResponse(BaseModel):
    """``GET /admin/orders`` payload."""

    model_config = ConfigDict(extra="forbid")

    orders: list[OrderSummary]
    total: int
    pending_count: int = 0
    live_count: int = 0
    status_filter: str | None = None


class OrderEventEntry(BaseModel):
    """One order lifecycle event."""

    model_config = ConfigDict(extra="forbid")

    source: str
    event_type: str
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime


class OrderEventsResponse(BaseModel):
    """``GET /admin/orders/{id}/events`` payload."""

    model_config = ConfigDict(extra="forbid")

    order_id: str
    events: list[OrderEventEntry]


class OrderReplaceRequest(BaseModel):
    """``POST /admin/orders/{id}/replace`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    qty: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)


class ReplaceOrderResponse(BaseModel):
    """``POST /admin/orders/{id}/replace`` response."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    qty: Decimal
    limit_price: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    audited: bool = True


class BlotterControlGapEntry(BaseModel):
    """Advisory gap for blotter control actions."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class BrokerStatusResponse(BaseModel):
    """``GET /admin/broker/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    broker_mode: str
    service_health: str
    service_reachable: bool | None = None
    message: str = ""
    positions_stale: bool = False
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    control_gaps: list[BlotterControlGapEntry] = Field(default_factory=list)
    checked_at: datetime


class BrokerAccountResponse(BaseModel):
    """``GET /admin/broker/account`` payload."""

    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    account_id: str
    external_id: str
    broker: str
    mode: str
    base_currency: str
    status: str
    portfolio_name: str


class BrokerPositionEntry(BaseModel):
    """One position row."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    portfolio_id: str
    qty: Decimal
    avg_entry_price: Decimal
    market_value: Decimal | None = None
    updated_at: datetime


class BrokerPositionsResponse(BaseModel):
    """``GET /admin/broker/positions`` payload."""

    model_config = ConfigDict(extra="forbid")

    source: str
    broker_reachable: bool
    stale: bool
    local: list[BrokerPositionEntry]
    broker: list[BrokerPositionEntry]


class BrokerOrdersResponse(BaseModel):
    """``GET /admin/broker/orders`` payload."""

    model_config = ConfigDict(extra="forbid")

    broker_reachable: bool
    orders: list[dict[str, Any]]


class BrokerFillEntry(BaseModel):
    """One execution/fill row."""

    model_config = ConfigDict(extra="forbid")

    id: int
    order_id: str
    client_order_id: str
    symbol: str
    ts: datetime
    qty: Decimal
    price: Decimal
    commission: Decimal


class BrokerFillsResponse(BaseModel):
    """``GET /admin/broker/fills`` payload."""

    model_config = ConfigDict(extra="forbid")

    fills: list[BrokerFillEntry]


class BrokerTestConnectionResponse(BaseModel):
    """``POST /admin/broker/test-connection`` response."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    detail: str
    audited: bool = True
    reason: str


class OmsStatusResponse(BaseModel):
    """``GET /admin/oms/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    service_health: str
    service_reachable: bool | None = None
    submissions_paused: bool
    checked_at: datetime


class OmsReconciliationResponse(BaseModel):
    """``GET /admin/oms/reconciliation`` payload."""

    model_config = ConfigDict(extra="forbid")

    submissions_paused: bool
    broker_reachable: bool
    drift_count: int
    position_drifts: list[dict[str, Any]]
    order_drifts: list[dict[str, Any]]
    last_checked_at: datetime | None = None
    last_checked_by: str | None = None
    control_gaps: list[BlotterControlGapEntry] = Field(default_factory=list)
    checked_at: datetime


class OmsReconciliationResolveResponse(BaseModel):
    """``POST /admin/oms/reconciliation/resolve`` response."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    submissions_paused: bool
    audited: bool = True
    reason: str


class MarketControlGapEntry(BaseModel):
    """Advisory gap for market data control actions."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class MarketDataRouteHealthEntry(BaseModel):
    """Health for one public Data API hostname."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    port: int
    health: str
    reachable: bool


class MarketDatasetFreshnessEntry(BaseModel):
    """Freshness for one dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset: str
    latest_date: str | None = None
    stale: bool


class MarketDataStatusResponse(BaseModel):
    """``GET /admin/market-data/status`` payload."""

    model_config = ConfigDict(extra="forbid")

    ingestion_health: str
    ingestion_reachable: bool | None = None
    snapshot_packager_health: str
    snapshot_packager_reachable: bool | None = None
    data_api_health: str
    data_api_public_routes: list[MarketDataRouteHealthEntry] = Field(default_factory=list)
    open_gap_count: int = 0
    price_gap_count: int = 0
    macro_gap_count: int = 0
    dataset_freshness: list[MarketDatasetFreshnessEntry] = Field(default_factory=list)
    stale_datasets: list[str] = Field(default_factory=list)
    universe_size: int = 0
    last_backfill_at: datetime | None = None
    last_backfill_by: str | None = None
    control_gaps: list[MarketControlGapEntry] = Field(default_factory=list)
    checked_at: datetime


class MarketDataProviderEntry(BaseModel):
    """One data provider / service."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    port: int
    worker: str | None = None
    health: str
    reachable: bool | None = None


class MarketDataProvidersResponse(BaseModel):
    """``GET /admin/market-data/providers`` payload."""

    model_config = ConfigDict(extra="forbid")

    providers: list[MarketDataProviderEntry]


class MarketDataGapEntry(BaseModel):
    """One row from audit_data_gaps."""

    model_config = ConfigDict(extra="forbid")

    id: int
    dataset_type: str
    trade_date: date | None = None
    severity: str
    remediation_state: str
    remediation_notes: str | None = None
    expected_count: int | None = None
    actual_count: int | None = None
    updated_at: datetime | None = None


class MarketDataGapListResponse(BaseModel):
    """``GET /admin/market-data/gaps`` payload."""

    model_config = ConfigDict(extra="forbid")

    gaps: list[MarketDataGapEntry]


class MarketDataGapResolveRequest(BaseModel):
    """``POST /admin/market-data/gaps/{id}/resolve`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class MarketDataGapResolveResponse(BaseModel):
    """``POST /admin/market-data/gaps/{id}/resolve`` response."""

    model_config = ConfigDict(extra="forbid")

    id: int
    dataset_type: str
    remediation_state: str
    audited: bool = True
    reason: str


class MarketBackfillRequest(BaseModel):
    """``POST /admin/market-data/backfill`` body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    adapter: str | None = None
    trading_date: date | None = None


class MarketBackfillResponse(BaseModel):
    """``POST /admin/market-data/backfill`` response."""

    model_config = ConfigDict(extra="forbid")

    mode: str
    result: dict[str, Any] = Field(default_factory=dict)
    audited: bool = True
    reason: str


class MarketUniverseResponse(BaseModel):
    """``GET /admin/market-data/universe`` payload."""

    model_config = ConfigDict(extra="forbid")

    active_instruments: int
    exchange_count: int
    editable: bool = False
    control_gaps: list[MarketControlGapEntry] = Field(default_factory=list)


class MarketCapEventEntry(BaseModel):
    """Corporate action used as market-cap related event proxy."""

    model_config = ConfigDict(extra="forbid")

    id: int
    symbol: str
    action_type: str
    ex_date: date | None = None
    amount: float | None = None


class MarketCapEventsResponse(BaseModel):
    """``GET /admin/market-data/market-cap-events`` payload."""

    model_config = ConfigDict(extra="forbid")

    events: list[MarketCapEventEntry]
    control_gaps: list[MarketControlGapEntry] = Field(default_factory=list)


class SnapshotSummaryEntry(BaseModel):
    """One packaged snapshot row."""

    model_config = ConfigDict(extra="forbid")

    id: str
    snapshot_id: str
    market: str
    trade_date: date
    universe_size: int
    packaged_at: datetime


class SnapshotListResponse(BaseModel):
    """``GET /admin/snapshots`` payload."""

    model_config = ConfigDict(extra="forbid")

    snapshots: list[SnapshotSummaryEntry]
    latest_market: str | None = None
    latest_trade_date: date | None = None


class SnapshotDetailResponse(BaseModel):
    """``GET /admin/snapshots/{id}`` payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    snapshot_id: str
    market: str
    trade_date: date
    schema_version: int
    blob_uri: str
    blob_sha256: str
    universe_size: int
    packaged_at: datetime
    packager_git_sha: str | None = None


class SnapshotArtifactEntry(BaseModel):
    """One snapshot artifact."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    uri: str
    sha256: str | None = None
    universe_size: int | None = None


class SnapshotArtifactsResponse(BaseModel):
    """``GET /admin/snapshots/{id}/artifacts`` payload."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    artifacts: list[SnapshotArtifactEntry]


class SnapshotBuildRequest(BaseModel):
    """``POST /admin/snapshots/build`` body."""

    model_config = ConfigDict(extra="forbid")

    market: str = Field(min_length=1, max_length=8)
    trading_date: date
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class SnapshotBuildResponse(BaseModel):
    """``POST /admin/snapshots/build`` response."""

    model_config = ConfigDict(extra="forbid")

    market: str
    trade_date: str
    snapshot_id: str
    blob_uri: str
    sha256: str
    universe_size: int
    mode: str
    audited: bool = True
    reason: str


class IntelligenceControlGapEntry(BaseModel):
    """Advisory gap for intelligence layer controls."""

    model_config = ConfigDict(extra="forbid")

    action: str
    reason: str


class RunAgentDangerousRequest(RunAgentRequest):
    """``POST /admin/agents/{id}/run`` body with audit confirmation."""

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class AgentDetailResponse(AgentSummary):
    """``GET /admin/agents/{id}`` payload."""

    paused: bool = False
    open_violation_count: int = 0
    cost_7d_usd: Decimal = Decimal("0")
    control_gaps: list[IntelligenceControlGapEntry] = Field(default_factory=list)


class AgentPauseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    paused: bool
    audited: bool = True
    reason: str


class AgentDisableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    active: bool
    audited: bool = True
    reason: str


class AgentConfigPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    model_default: str | None = Field(default=None, max_length=128)
    model_fallback: str | None = Field(default=None, max_length=128)


class AgentConfigPatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    model_default: str
    model_fallback: str | None
    audited: bool = True
    reason: str


class AgentVersionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    label: str
    constitution_path: str
    content_hash: str | None = None
    created_at: datetime
    created_by: str


class AgentVersionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    versions: list[AgentVersionEntry]


class AgentRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class AgentRollbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    version_id: UUID
    constitution_path: str
    mode: str
    audited: bool = True
    reason: str
    notes: str | None = None


class ProposalDangerousActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool
    review_notes: str | None = Field(default=None, max_length=2000)


class ProposalActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    reviewed_by: str
    reviewed_at: datetime
    review_notes: str | None = None
    audited: bool = True
    reason: str


class BacktestDetailResponse(BacktestRunSummary):
    """``GET /admin/backtests/{id}`` payload."""

    control_gaps: list[IntelligenceControlGapEntry] = Field(default_factory=list)


class BacktestCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class BacktestCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    mode: str
    audited: bool = True
    reason: str


class BacktestRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class BacktestRetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    new_backtest_run_id: UUID
    status: str
    audited: bool = True
    reason: str


class BacktestArtifactEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    uri: str


class BacktestArtifactsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backtest_run_id: UUID
    artifacts: list[BacktestArtifactEntry]


class ReportBriefingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    status: str
    generated_at: datetime
    stale_after: datetime | None = None
    summary: str | None = None


class ReportListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    briefings: list[ReportBriefingEntry]
    stale_count: int = 0
    control_gaps: list[IntelligenceControlGapEntry] = Field(default_factory=list)


class ReportRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class ReportRegenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    status: str
    mode: str
    audited: bool = True
    reason: str


class ReportExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    export_uri: str | None = None
    status: str


class CostsOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int
    total_cost_usd: Decimal
    daily: list[DailyCostEntry]
    month: str
    agent_total_usd: Decimal
    vendor_rows: list[dict[str, Any]]
    kill_switch_active: bool


class CostsBudgetEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    scope: str
    monthly_limit_usd: Decimal
    warn_threshold_pct: Decimal
    updated_at: datetime
    updated_by: str | None = None


class CostsBudgetsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budgets: list[CostsBudgetEntry]
    kill_switch_active: bool
    kill_switch_reason: str | None = None


class CostsBudgetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(min_length=1, max_length=64)
    monthly_limit_usd: Decimal = Field(gt=0)
    warn_threshold_pct: Decimal = Field(gt=0, le=100)
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class CostsKillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str = Field(min_length=1, max_length=2000)
    confirm: bool


class CostsKillSwitchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kill_switch_active: bool
    kill_switch_reason: str | None = None
    audited: bool = True
    reason: str


class CommandDefinitionEntry(BaseModel):
    """One allowlisted command in the registry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    example: str
    description: str
    role_required: str
    backend_route: str
    dangerous: bool
    confirmation_required: bool
    reason_required: bool
    audit_category: str
    preview_output: str
    rollback_note: str


class CommandListResponse(BaseModel):
    """``GET /admin/commands`` payload."""

    model_config = ConfigDict(extra="forbid")

    commands: list[CommandDefinitionEntry]


class CommandPreviewRequest(BaseModel):
    """``POST /admin/commands/preview`` body."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)


class CommandPreviewResponse(BaseModel):
    """``POST /admin/commands/preview`` response."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID | None = None
    command_id: str | None = None
    command_text: str
    description: str | None = None
    role_required: str | None = None
    backend_route: str | None = None
    dangerous: bool = False
    confirmation_required: bool = False
    reason_required: bool = False
    audit_category: str | None = None
    preview_output: str | None = None
    rollback_note: str | None = None
    consequence_preview: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    allowed: bool
    denial_reason: str | None = None


class CommandRunRequest(BaseModel):
    """``POST /admin/commands/run`` body."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)
    confirm: bool = False


class CommandRunResponse(BaseModel):
    """``POST /admin/commands/run`` response."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    command_id: str
    command_text: str
    status: str
    backend_route: str
    audit_category: str
    result: dict[str, Any] = Field(default_factory=dict)
    audited: bool = True


class CommandRunSummaryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    command_id: str
    command_text: str
    actor: str
    status: str
    backend_route: str
    audit_category: str
    created_at: datetime
    completed_at: datetime | None = None


class CommandRunsListResponse(BaseModel):
    """``GET /admin/commands/runs`` payload."""

    model_config = ConfigDict(extra="forbid")

    runs: list[CommandRunSummaryEntry]


class CommandRunDetailResponse(BaseModel):
    """``GET /admin/commands/runs/{id}`` payload."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    command_id: str
    command_text: str
    actor: str
    reason: str | None = None
    status: str
    backend_route: str
    audit_category: str
    preview: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    audit_link: str
