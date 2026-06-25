"""Compare repo, host, runtime, and remote Cloudflare config for edge drift."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from edge.canonical_routes import (
    UNREGISTERED_INCIDENT_PORTS,
    CanonicalRouteSeed,
)
from edge.config_reader import parse_service_url_target
from zinc_schemas.admin_dto import EdgeDriftStatus


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Parsed config sources for drift comparison."""

    repo_routes: dict[str, str]
    repo_status: str
    host_routes: dict[str, str]
    host_status: str
    runtime_trusted_hosts: list[str]
    runtime_trusted_status: str
    repo_example_trusted_hosts: list[str]
    remote_routes: dict[str, str]
    remote_status: str


def compute_route_drift(
    seed: CanonicalRouteSeed,
    *,
    repo_target: str | None,
    host_target: str | None,
    remote_target: str | None,
    port_listening: bool | None,
    health_status: str,
    trusted_host_present: bool | None,
    checked_at: datetime,
) -> EdgeDriftStatus:
    """Derive drift status for one canonical route."""
    messages: list[str] = []
    status = "ok"
    action: str | None = None

    actual_target = host_target or repo_target
    actual_host, actual_port = parse_service_url_target(actual_target or "")

    if actual_port in UNREGISTERED_INCIDENT_PORTS:
        status = "critical"
        messages.append(
            f"Tunnel targets unregistered incident port {actual_port} (e.g. :9500 → 502).",
        )
        action = f"Fix tunnel ingress to 127.0.0.1:{seed.expected_internal_port} and restart cloudflared."

    if actual_host and actual_port is not None:
        if (
            actual_host != seed.expected_internal_host
            or actual_port != seed.expected_internal_port
        ):
            if status != "critical":
                status = "port_mismatch" if actual_port != seed.expected_internal_port else "tunnel_mismatch"
            messages.append(
                f"Actual tunnel target {actual_host}:{actual_port} "
                f"≠ expected {seed.expected_internal_host}:{seed.expected_internal_port}.",
            )
            action = action or (
                f"Update tunnel route to http://{seed.expected_internal_host}:"
                f"{seed.expected_internal_port}."
            )

    if host_target and repo_target and host_target != repo_target:
        if status == "ok":
            status = "tunnel_mismatch"
        messages.append(f"Host config target {host_target} ≠ repo config {repo_target}.")

    if remote_target and actual_target and remote_target != actual_target:
        if status == "ok":
            status = "tunnel_mismatch"
        messages.append(f"Remote Cloudflare ingress {remote_target} ≠ local {actual_target}.")

    if seed.hostname == "dataapiprod.theeyebeta.store" and not repo_target and not host_target:
        if status == "ok":
            status = "config_missing"
        messages.append("Hostname not in committed repo cloudflared-config.yml.")

    if seed.trusted_host_required and trusted_host_present is False:
        if status in {"ok", "config_missing"}:
            status = "host_header_risk"
        messages.append(
            f"TRUSTED_HOSTS missing {seed.hostname} — Data API returns 400 Invalid host header.",
        )
        action = action or f"Add {seed.hostname} to TRUSTED_HOSTS and restart theeyebeta-dataapi."

    if port_listening is False:
        if status == "ok":
            status = "port_not_listening"
        messages.append(
            f"Nothing listening on {seed.expected_internal_host}:{seed.expected_internal_port}.",
        )
        action = action or f"Start {seed.systemd_unit or seed.expected_service_name} on port {seed.expected_internal_port}."

    if health_status == "unhealthy":
        if status == "ok":
            status = "health_unhealthy"
        messages.append(f"Health check failed for {seed.health_endpoint}.")

    if not messages and status == "ok":
        return EdgeDriftStatus(status="ok", messages=[], action_needed=None)

    return EdgeDriftStatus(status=status, messages=messages, action_needed=action)


def is_drift_critical(drift: EdgeDriftStatus) -> bool:
    return drift.status in {
        "critical",
        "port_mismatch",
        "tunnel_mismatch",
        "host_header_risk",
        "port_not_listening",
    }


def build_drift_alerts(routes: list) -> list[str]:
    """Build operator-facing alert strings from route entries."""
    alerts: list[str] = []
    for route in routes:
        if is_drift_critical(route.drift):
            alerts.append(
                f"CRITICAL [{route.hostname}]: {route.drift.status} — "
                f"{'; '.join(route.drift.messages)}",
            )
    return alerts
