"""Static expected registries for matrix staleness checks.

Dynamic FastAPI route discovery is deferred — this module is the CI guard
until ``collect_routes_from_app()`` lands. Update mappings when adding routers,
workers, services, or allowlisted commands.
"""

from __future__ import annotations

# Each mounted admin API router prefix must map to at least one matrix entry id.
ADMIN_API_MODULE_MATRIX_IDS: dict[str, tuple[str, ...]] = {
    "orders": ("admin.orders.blotter", "admin.page.orders"),
    "audit": ("admin.page.audit",),
    "agents": ("admin.agents.detail", "admin.page.agents", "admin.action.run-agent"),
    "guard": ("admin.page.violations", "admin.action.resolve-violation"),
    "services": ("admin.services.control-plane", "admin.action.restart-service"),
    "backtest": ("admin.action.start-backtest",),
    "costs": ("admin.page.costs", "costs.kill_switch", "costs.budget.patch"),
    "sql": ("admin.page.sql", "admin.action.sql-execute"),
    "proposals": ("admin.page.proposals", "admin.proposals.actions", "admin.action.approve-proposal"),
    "master-admin": ("master-admin.control-matrix", "master-admin.rbac"),
    "cloudflare": ("cloudflare.status.module",),
    "edge": ("edge.registry.module", "edge.drift.tunnel-port-mismatch"),
    "users": ("admin.users.control-plane",),
    "workers": ("admin.workers.control-plane",),
    "timers": ("admin.workers.control-plane",),
    "trading": ("admin.trading.control-plane", "trading.emergency-halt"),
    "risk": ("admin.risk.control-plane",),
    "compliance": ("admin.compliance.control-plane",),
    "broker": ("admin.broker.blotter",),
    "oms": ("oms.reconciliation.resolve", "trading.oms-submission-gate"),
    "market-data": ("admin.market-data.status",),
    "snapshots": ("admin.snapshots.list",),
    "pipelines": ("admin.pipelines.status",),
    "backtests": ("admin.backtests.cockpit",),
    "reports": ("admin.reports.cockpit",),
    "commands": ("admin.commands.registry", "admin.commands.run", "admin.commands.preview"),
}

# Routers mounted under /admin that are intentionally excluded from matrix parity.
ADMIN_API_EXEMPT_PREFIXES: frozenset[str] = frozenset(
    {
        "auth",  # login/session — not an operator capability row
        "static",  # assets
    },
)

# Allowlisted command id -> matrix entry ids that represent the backend capability.
COMMAND_MATRIX_REPRESENTATION: dict[str, tuple[str, ...]] = {
    "worker.run": ("admin.workers.control-plane",),
    "worker.stop": ("admin.workers.control-plane",),
    "timer.disable": ("admin.workers.control-plane",),
    "service.restart": ("admin.services.control-plane", "admin.action.restart-service"),
    "edge.routes.check": ("command.edge.routes.check", "edge.registry.module"),
    "cloudflare.status": ("cloudflare.status.module",),
    "dataapi.health": ("admin.market-data.status", "edge.data-api.public-routing"),
    "trading.halt": ("trading.emergency-halt",),
    "audit.verify": ("command.verify-audit-chain", "admin.page.audit"),
    "risk.compute": ("admin.risk.control-plane",),
    "broker.test": ("admin.broker.blotter",),
    "backtest.run": ("admin.backtests.cockpit", "admin.action.start-backtest"),
    "agent.run": ("agent.run", "admin.action.run-agent"),
}

# Canonical hostname -> matrix edge.route entry id.
CANONICAL_HOSTNAME_MATRIX_IDS: dict[str, str] = {
    "dataapi.theeyebeta.store": "edge.route.dataapi-theeyebeta-store",
    "dataapiprod.theeyebeta.store": "edge.route.dataapiprod-theeyebeta-store",
    "api.theeyebeta.store": "edge.route.api-theeyebeta-store",
    "admin.theeyebeta.store": "edge.route.admin-theeyebeta-store",
}

# Hostnames requiring TRUSTED_HOSTS matrix rows.
TRUSTED_HOST_MATRIX_IDS: dict[str, str] = {
    "dataapi.theeyebeta.store": "trusted-hosts.dataapi-theeyebeta-store",
    "dataapiprod.theeyebeta.store": "trusted-hosts.dataapiprod-theeyebeta-store",
}

# Required structural matrix entry ids (edge + platform modules).
REQUIRED_MATRIX_ENTRY_IDS: frozenset[str] = frozenset(
    {
        "edge.registry.module",
        "cloudflare.status.module",
        "edge.data-api.public-routing",
        "edge.port.sentinel-unregistered-9500",
        "edge.drift.tunnel-port-mismatch",
        "edge.drift.trusted-host-missing",
        "edge.drift.port-service-mismatch",
        "port.registry.data-api-7000",
        "master-admin.control-matrix",
        "admin.commands.registry",
    },
)
