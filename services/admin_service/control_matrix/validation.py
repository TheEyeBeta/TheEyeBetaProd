"""Invariant checks for the MASTER_ADMIN control matrix."""

from __future__ import annotations

from zinc_schemas.admin_dto import ControlMatrixEntry

# Ports registered as expected service targets (not drift sentinels).
EXPECTED_SERVICE_PORTS: frozenset[int] = frozenset({7000, 7200, 8000, 8090})

# Incident-class port — must never appear as an expected route target.
UNREGISTERED_INCIDENT_PORT = 9500

REQUIRED_CATEGORIES: frozenset[str] = frozenset(
    {
        "Cloudflare/Edge",
        "Edge Route Registry",
        "Data API public routing",
        "Trusted Hosts",
        "Service Port Registry",
    }
)


def validate_matrix_invariants(entries: list[ControlMatrixEntry]) -> list[str]:
    """Return human-readable violations; empty list means all invariants hold."""
    errors: list[str] = []
    by_id = {e.id: e for e in entries}
    categories = {e.category for e in entries}

    missing_cats = REQUIRED_CATEGORIES - categories
    if missing_cats:
        errors.append(f"Missing required categories: {sorted(missing_cats)}")

    for entry in entries:
        if entry.dangerous:
            if not entry.confirmation_required:
                errors.append(f"{entry.id}: dangerous action missing confirmation_required")
            if not entry.audit_required:
                errors.append(f"{entry.id}: dangerous action missing audit_required")

        if entry.backend_only_reason and entry.controllable:
            errors.append(
                f"{entry.id}: backend-only entry must not be controllable",
            )

        if (
            not entry.viewable
            and not entry.backend_only_reason
            and not entry.backend_gap
            and not entry.frontend_gap
        ):
            errors.append(
                f"{entry.id}: non-viewable entry requires backend_only_reason or backend_gap",
            )

    for entry in entries:
        if entry.service_port_dependency and ":9500" in entry.service_port_dependency:
            if not entry.id.startswith("edge.port.") and "sentinel" not in entry.id:
                errors.append(
                    f"{entry.id}: port 9500 must not be an expected route target",
                )

    dataapi = by_id.get("edge.route.dataapi-theeyebeta-store")
    dataapiprod = by_id.get("edge.route.dataapiprod-theeyebeta-store")
    for label, row in ("dataapi", dataapi), ("dataapiprod", dataapiprod):
        if row is None:
            errors.append(f"Missing matrix entry for {label}.theeyebeta.store")
            continue
        if row.service_port_dependency != "127.0.0.1:7000":
            errors.append(f"{row.id}: expected service_port_dependency 127.0.0.1:7000")

    sentinel = by_id.get("edge.port.sentinel-unregistered-9500")
    if sentinel is None:
        errors.append("Missing port 9500 drift sentinel entry")
    elif sentinel.controllable or sentinel.viewable is False:
        errors.append("Port 9500 sentinel must be viewable and not controllable")

    return errors


def collect_drift_alerts(entries: list[ControlMatrixEntry]) -> list[str]:
    """Build Critical drift alert strings for operator display."""
    alerts: list[str] = []

    for entry in entries:
        if entry.id == "edge.drift.tunnel-port-mismatch":
            alerts.append(
                "CRITICAL: Cloudflare tunnel port drift (e.g. :9500 vs :7000) causes 502 — "
                "see dataapiprod incident; reconcile via Edge Route Registry.",
            )
        if entry.id == "edge.drift.trusted-host-missing":
            alerts.append(
                "CRITICAL: Public hostname in tunnel but missing from TRUSTED_HOSTS "
                "causes 400 Invalid host header after route fix.",
            )
        if entry.id == "edge.route.dataapiprod-theeyebeta-store" and entry.backend_gap:
            alerts.append(
                f"CRITICAL: {entry.title} — {entry.backend_gap}",
            )

    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for msg in alerts:
        if msg not in seen:
            seen.add(msg)
            unique.append(msg)
    return unique
