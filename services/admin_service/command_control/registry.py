"""Allowlisted command definitions — maps CLI phrases to backend APIs only."""

from __future__ import annotations

from dataclasses import dataclass

WORKER_ALIASES: dict[str, str] = {
    "macro-ingestion": "macro",
    "macro": "macro",
    "massive-ingestion": "massive-ingest",
    "massive-ingest": "massive-ingest",
}

TIMER_ALIASES: dict[str, str] = {
    "daily-pipeline": "daily-pipeline",
}

SERVICE_ALIASES: dict[str, str] = {
    "theeyebeta-dataapi.service": "data-api",
    "theeyebeta-dataapi": "data-api",
    "data-api": "data-api",
}

AGENT_ALIASES: dict[str, str] = {
    "market-trio": "technical-analyst",
    "technical-analyst": "technical-analyst",
    "macro-lead": "macro-lead",
}


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """One allowlisted operator command."""

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


COMMANDS: tuple[CommandDefinition, ...] = (
    CommandDefinition(
        id="worker.run",
        example="WORKER RUN macro --date today",
        description="Force-run an allowlisted worker via Workers control plane.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/workers/{name}/run",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Workers/Schedulers",
        preview_output="Triggers systemd/service run for the worker; --date is advisory only.",
        rollback_note="Cannot undo a run; inspect worker runs and downstream data freshness.",
    ),
    CommandDefinition(
        id="worker.stop",
        example="WORKER STOP massive-ingest",
        description="Stop an allowlisted worker process.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/workers/{name}/stop",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Workers/Schedulers",
        preview_output="Sends stop to the worker systemd unit when live mode is available.",
        rollback_note="Re-run the worker or resume timer schedule manually.",
    ),
    CommandDefinition(
        id="timer.disable",
        example="TIMER DISABLE daily-pipeline",
        description="Disable a systemd timer in the allowlisted registry.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/timers/{name}/disable",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Workers/Schedulers",
        preview_output="Disables the timer unit; scheduled ingest will not fire until re-enabled.",
        rollback_note="TIMER ENABLE {name} via Timers panel or POST /admin/timers/{name}/enable.",
    ),
    CommandDefinition(
        id="service.restart",
        example="SERVICE RESTART theeyebeta-dataapi.service",
        description="Restart an allowlisted systemd service (no arbitrary systemctl).",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/services/{name}/restart",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Services/systemd",
        preview_output="Restarts only services in services_control/registry.py.",
        rollback_note="Service should recover automatically; check /admin/services for health.",
    ),
    CommandDefinition(
        id="edge.routes.check",
        example="EDGE ROUTES CHECK",
        description="Refresh edge route drift probes (read-only checks, audited).",
        role_required="operator",
        backend_route="POST /admin/edge/routes/check",
        dangerous=False,
        confirmation_required=False,
        reason_required=False,
        audit_category="Edge",
        preview_output="Re-runs canonical route probes and TRUSTED_HOSTS drift comparison.",
        rollback_note="Read-only; no rollback required.",
    ),
    CommandDefinition(
        id="cloudflare.status",
        example="CLOUDFLARE STATUS",
        description="Fetch redacted Cloudflare tunnel and DNS summary.",
        role_required="operator",
        backend_route="GET /admin/cloudflare/status",
        dangerous=False,
        confirmation_required=False,
        reason_required=False,
        audit_category="Edge",
        preview_output="Returns tunnel mode, route count, and drift hints without secrets.",
        rollback_note="Read-only.",
    ),
    CommandDefinition(
        id="dataapi.health",
        example="DATAAPI HEALTH",
        description="Probe Data API internal and public route health.",
        role_required="operator",
        backend_route="GET /admin/market-data/status",
        dangerous=False,
        confirmation_required=False,
        reason_required=False,
        audit_category="Data API",
        preview_output="Summarises :7000 health and dataapi hostnames.",
        rollback_note="Read-only; use SERVICE RESTART for recovery.",
    ),
    CommandDefinition(
        id="trading.halt",
        example="TRADING HALT",
        description="Activate emergency trading halt gate.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/trading/emergency-halt",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Emergency Trading",
        preview_output="Sets emergency halt; blocks live submissions until resume.",
        rollback_note="POST /admin/trading/resume-from-halt after incident review.",
    ),
    CommandDefinition(
        id="audit.verify",
        example="AUDIT VERIFY 24H",
        description="Verify audit hash chain over a trailing window.",
        role_required="operator",
        backend_route="GET audit-service /audit/verify",
        dangerous=False,
        confirmation_required=False,
        reason_required=False,
        audit_category="Audit",
        preview_output="Proxies to audit-service verify for the requested hours window.",
        rollback_note="Read-only verification.",
    ),
    CommandDefinition(
        id="risk.compute",
        example="RISK COMPUTE main",
        description="Recompute risk metrics for a portfolio.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/risk/compute",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Risk",
        preview_output="Invokes risk-service compute for the portfolio id.",
        rollback_note="Metrics recompute is idempotent; prior snapshots remain in history.",
    ),
    CommandDefinition(
        id="broker.test",
        example="BROKER TEST alpaca",
        description="Test broker connectivity (allowlisted brokers only).",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/broker/test-connection",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Broker/Portfolio",
        preview_output="Pings configured broker adapter; does not submit orders.",
        rollback_note="No state change beyond audit log.",
    ),
    CommandDefinition(
        id="backtest.run",
        example="BACKTEST RUN strategy=momentum-v1 universe=sp500",
        description="Start a backtest via backtest-engine allowlist.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/backtests",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Backtests",
        preview_output="Enqueues backtest-engine run with parsed strategy/universe.",
        rollback_note="POST /admin/backtests/{id}/cancel if still running.",
    ),
    CommandDefinition(
        id="agent.run",
        example="AGENT RUN market-trio",
        description="Trigger an allowlisted agent run via agent-runtime.",
        role_required="MASTER_ADMIN",
        backend_route="POST /admin/agents/{id}/run",
        dangerous=True,
        confirmation_required=True,
        reason_required=True,
        audit_category="Agents",
        preview_output="Uses latest packaged snapshot; market-trio aliases technical-analyst.",
        rollback_note="Agent run is append-only; review run output and costs.",
    ),
)

COMMANDS_BY_ID: dict[str, CommandDefinition] = {cmd.id: cmd for cmd in COMMANDS}
