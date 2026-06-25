"""Cross-registry staleness checks — matrix must mirror backend capabilities."""

from __future__ import annotations

from command_control.registry import COMMANDS
from control_matrix.expected_registry import (
    ADMIN_API_EXEMPT_PREFIXES,
    ADMIN_API_MODULE_MATRIX_IDS,
    CANONICAL_HOSTNAME_MATRIX_IDS,
    COMMAND_MATRIX_REPRESENTATION,
    REQUIRED_MATRIX_ENTRY_IDS,
    TRUSTED_HOST_MATRIX_IDS,
)
from control_matrix.validation import EXPECTED_SERVICE_PORTS, UNREGISTERED_INCIDENT_PORT
from edge.canonical_routes import CANONICAL_ROUTES, UNREGISTERED_INCIDENT_PORTS
from frontend_ia.modules import TERMINAL_MODULES
from services_control.registry import CANONICAL_SERVICES, expected_ports
from workers_control.registry import CANONICAL_TIMERS, CANONICAL_WORKERS
from zinc_schemas.admin_dto import ControlMatrixEntry

# Future: replace static ADMIN_API_MODULE_MATRIX_IDS with FastAPI route introspection.
FUTURE_DYNAMIC_DISCOVERY = (
    "Dynamic admin route discovery from FastAPI app.routes is planned; "
    "static expected_registry.py is the CI guard until then."
)


def collect_registry_staleness(entries: list[ControlMatrixEntry]) -> list[str]:
    """Compare sibling registries to the control matrix; return violation messages."""
    errors: list[str] = []
    by_id = {entry.id: entry for entry in entries}
    matrix_ids = set(by_id)

    errors.extend(_check_required_entries(matrix_ids))
    errors.extend(_check_admin_api_modules(matrix_ids))
    errors.extend(_check_workers(matrix_ids))
    errors.extend(_check_timers(matrix_ids))
    errors.extend(_check_services(matrix_ids, by_id))
    errors.extend(_check_commands(matrix_ids))
    errors.extend(_check_dangerous_audit_metadata(entries))
    errors.extend(_check_canonical_routes(by_id))
    errors.extend(_check_port_registry(by_id))
    errors.extend(_check_trusted_hosts(by_id))
    errors.extend(_check_health_endpoints(by_id))
    from frontend_ia.nav import validate_nav_against_matrix

    errors.extend(validate_nav_against_matrix())
    errors.extend(_check_command_registry_sync())

    return errors


def collect_staleness_alerts(entries: list[ControlMatrixEntry]) -> list[str]:
    """Human-readable alerts for matrix API responses."""
    return [f"STALENESS: {msg}" for msg in collect_registry_staleness(entries)]


def _check_required_entries(matrix_ids: set[str]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_MATRIX_ENTRY_IDS - matrix_ids
    if missing:
        errors.append(f"Missing required matrix entries: {sorted(missing)}")
    return errors


def _check_admin_api_modules(matrix_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for prefix, required_ids in ADMIN_API_MODULE_MATRIX_IDS.items():
        if prefix in ADMIN_API_EXEMPT_PREFIXES:
            continue
        if not any(entry_id in matrix_ids for entry_id in required_ids):
            errors.append(
                f"Admin API /admin/{prefix} missing matrix representation "
                f"(expected one of {required_ids})",
            )
    return errors


def _check_workers(matrix_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for worker in CANONICAL_WORKERS:
        entry_id = f"worker.{worker.key}"
        if entry_id not in matrix_ids:
            errors.append(f"Worker {worker.key!r} missing matrix entry {entry_id!r}")
    return errors


def _check_timers(matrix_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for timer in CANONICAL_TIMERS:
        worker_entry = f"worker.{timer.worker_key}"
        if worker_entry not in matrix_ids:
            errors.append(
                f"Timer {timer.key!r} missing matrix representation via {worker_entry!r}",
            )
    return errors


def _check_services(
    matrix_ids: set[str],
    by_id: dict[str, ControlMatrixEntry],
) -> list[str]:
    errors: list[str] = []
    for service in CANONICAL_SERVICES:
        entry_id = f"service.systemd.{service.key}"
        if entry_id not in matrix_ids:
            errors.append(f"Service {service.key!r} missing matrix entry {entry_id!r}")
            continue
        row = by_id[entry_id]
        if service.port is not None and row.service_port_dependency is not None:
            expected = f"127.0.0.1:{service.port}"
            if row.service_port_dependency != expected:
                errors.append(
                    f"{entry_id}: service registry port {service.port} "
                    f"!= matrix {row.service_port_dependency!r}",
                )
        if service.health_endpoint and not row.health_endpoint:
            errors.append(f"{entry_id}: missing health_endpoint in matrix")
    return errors


def _check_commands(matrix_ids: set[str]) -> list[str]:
    errors: list[str] = []
    command_ids = {cmd.id for cmd in COMMANDS}
    for cmd_id, required in COMMAND_MATRIX_REPRESENTATION.items():
        if cmd_id not in command_ids:
            errors.append(f"Stale command mapping: unknown command id {cmd_id!r}")
            continue
        if not any(entry_id in matrix_ids for entry_id in required):
            errors.append(
                f"Command {cmd_id!r} missing matrix representation (expected one of {required})",
            )
    for cmd in COMMANDS:
        if cmd.id not in COMMAND_MATRIX_REPRESENTATION:
            errors.append(f"Command {cmd.id!r} missing from COMMAND_MATRIX_REPRESENTATION")
    return errors


def _check_dangerous_audit_metadata(entries: list[ControlMatrixEntry]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        if not entry.dangerous:
            continue
        if not entry.audit_required:
            errors.append(f"{entry.id}: dangerous action missing audit_required")
        if entry.controllable and not entry.audit_implemented:
            errors.append(
                f"{entry.id}: controllable dangerous action missing audit_implemented",
            )
    for cmd in COMMANDS:
        if cmd.dangerous and not cmd.audit_category:
            errors.append(f"Command {cmd.id}: dangerous command missing audit_category")
    return errors


def _check_canonical_routes(by_id: dict[str, ControlMatrixEntry]) -> list[str]:
    errors: list[str] = []
    for route in CANONICAL_ROUTES:
        entry_id = CANONICAL_HOSTNAME_MATRIX_IDS.get(route.hostname)
        if entry_id is None:
            errors.append(f"Canonical route {route.hostname!r} missing hostname mapping")
            continue
        row = by_id.get(entry_id)
        if row is None:
            errors.append(f"Canonical route {route.hostname!r} missing matrix entry {entry_id!r}")
            continue
        expected_port = f"127.0.0.1:{route.expected_internal_port}"
        if row.service_port_dependency != expected_port:
            errors.append(
                f"{entry_id}: {route.hostname} must map to {expected_port}, "
                f"matrix has {row.service_port_dependency!r}",
            )
        if route.hostname == "dataapi.theeyebeta.store" and route.expected_internal_port != 7000:
            errors.append("dataapi.theeyebeta.store must map to port 7000")
        if route.hostname == "dataapiprod.theeyebeta.store" and route.expected_internal_port != 7000:
            errors.append("dataapiprod.theeyebeta.store must map to port 7000")
    return errors


def _check_port_registry(by_id: dict[str, ControlMatrixEntry]) -> list[str]:
    errors: list[str] = []
    registered = expected_ports()
    for port, service_key in registered.items():
        if port in UNREGISTERED_INCIDENT_PORTS:
            errors.append(f"Port {port} registered to {service_key} but is incident-class")
        if port not in EXPECTED_SERVICE_PORTS and port not in {7000, 7200, 8000, 8090, 7020, 4222, 6379}:
            # Extend allowed set with infra ports used by services registry.
            pass

    for entry in by_id.values():
        dep = entry.service_port_dependency or ""
        if f":{UNREGISTERED_INCIDENT_PORT}" in dep:
            if entry.id != "edge.port.sentinel-unregistered-9500":
                errors.append(
                    f"{entry.id}: port {UNREGISTERED_INCIDENT_PORT} is not an expected route target",
                )

    sentinel = by_id.get("edge.port.sentinel-unregistered-9500")
    if sentinel is None:
        errors.append("Missing port 9500 drift sentinel matrix entry")
    elif f":{UNREGISTERED_INCIDENT_PORT}" not in (sentinel.service_port_dependency or ""):
        errors.append("Port 9500 sentinel must document :9500 as incident-only")

    data_api_row = by_id.get("port.registry.data-api-7000")
    if data_api_row is None:
        errors.append("Missing port.registry.data-api-7000 matrix entry")
    elif data_api_row.service_port_dependency != "127.0.0.1:7000":
        errors.append("port.registry.data-api-7000 must map to 127.0.0.1:7000")

    return errors


def _check_trusted_hosts(by_id: dict[str, ControlMatrixEntry]) -> list[str]:
    errors: list[str] = []
    for route in CANONICAL_ROUTES:
        if not route.trusted_host_required:
            continue
        entry_id = TRUSTED_HOST_MATRIX_IDS.get(route.hostname)
        if entry_id is None:
            errors.append(f"Trusted host requirement for {route.hostname!r} has no matrix mapping")
            continue
        row = by_id.get(entry_id)
        if row is None:
            errors.append(f"Missing trusted-host matrix entry {entry_id!r}")
        elif not row.trusted_host_dependency:
            errors.append(f"{entry_id}: trusted_host_dependency must be true")
    drift_row = by_id.get("edge.drift.trusted-host-missing")
    if drift_row is None:
        errors.append("Missing edge.drift.trusted-host-missing detection entry")
    return errors


def _check_health_endpoints(by_id: dict[str, ControlMatrixEntry]) -> list[str]:
    errors: list[str] = []
    for route in CANONICAL_ROUTES:
        entry_id = CANONICAL_HOSTNAME_MATRIX_IDS.get(route.hostname)
        if not entry_id:
            continue
        row = by_id.get(entry_id)
        if row is None:
            continue
        if route.health_endpoint and not row.health_endpoint:
            errors.append(f"{entry_id}: missing health_endpoint for {route.hostname}")
    for service in CANONICAL_SERVICES:
        if not service.health_endpoint or service.port is None:
            continue
        row = by_id.get(f"service.systemd.{service.key}")
        if row and not row.health_endpoint:
            errors.append(f"service.systemd.{service.key}: missing health_endpoint")
    return errors


def _check_command_registry_sync() -> list[str]:
    errors: list[str] = []
    if len(COMMANDS) != len(COMMAND_MATRIX_REPRESENTATION):
        errors.append(
            f"Command allowlist ({len(COMMANDS)}) and matrix mapping "
            f"({len(COMMAND_MATRIX_REPRESENTATION)}) out of sync",
        )
    return errors


def summarize_implemented_modules() -> list[str]:
    """Return nav module keys that are implemented — used in tests."""
    return [module.key for module in TERMINAL_MODULES if module.implemented]
