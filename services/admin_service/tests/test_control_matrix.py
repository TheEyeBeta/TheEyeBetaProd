"""Tests for MASTER_ADMIN control matrix."""

from __future__ import annotations

from typing import Any

import pytest
from control_matrix.registry import build_control_matrix, build_control_matrix_response
from control_matrix.staleness import (
    FUTURE_DYNAMIC_DISCOVERY,
    collect_registry_staleness,
    collect_staleness_alerts,
)
from control_matrix.validation import (
    REQUIRED_CATEGORIES,
    collect_drift_alerts,
    validate_matrix_invariants,
)
from httpx import AsyncClient


def _ids(entries: list[Any]) -> set[str]:
    return {e.id for e in entries}


@pytest.mark.unit
def test_registry_staleness_checks_pass() -> None:
    """Sibling registries (workers, services, commands, edge) match the matrix."""
    entries = build_control_matrix()
    violations = collect_registry_staleness(entries)
    assert violations == [], f"Matrix staleness violations: {violations}"


@pytest.mark.unit
def test_staleness_alerts_empty_when_registry_synced() -> None:
    alerts = collect_staleness_alerts(build_control_matrix())
    assert alerts == []


@pytest.mark.unit
def test_every_admin_api_module_has_matrix_row() -> None:
    from control_matrix.expected_registry import ADMIN_API_MODULE_MATRIX_IDS

    ids = _ids(build_control_matrix())
    for prefix, required in ADMIN_API_MODULE_MATRIX_IDS.items():
        assert any(entry_id in ids for entry_id in required), (
            f"/admin/{prefix} missing matrix row (expected one of {required})"
        )


@pytest.mark.unit
def test_every_command_has_matrix_representation() -> None:
    from command_control.registry import COMMANDS
    from control_matrix.expected_registry import COMMAND_MATRIX_REPRESENTATION

    ids = _ids(build_control_matrix())
    for cmd in COMMANDS:
        required = COMMAND_MATRIX_REPRESENTATION[cmd.id]
        assert any(entry_id in ids for entry_id in required), (
            f"Command {cmd.id} missing matrix representation"
        )


@pytest.mark.unit
def test_every_worker_and_timer_in_matrix() -> None:
    from workers_control.registry import CANONICAL_TIMERS, CANONICAL_WORKERS

    ids = _ids(build_control_matrix())
    for worker in CANONICAL_WORKERS:
        assert f"worker.{worker.key}" in ids
    for timer in CANONICAL_TIMERS:
        assert f"worker.{timer.worker_key}" in ids


@pytest.mark.unit
def test_every_service_in_matrix_with_port_parity() -> None:
    from services_control.registry import CANONICAL_SERVICES

    entries = {e.id: e for e in build_control_matrix()}
    for service in CANONICAL_SERVICES:
        row = entries[f"service.systemd.{service.key}"]
        if service.port is not None and row.service_port_dependency is not None:
            assert row.service_port_dependency == f"127.0.0.1:{service.port}"


@pytest.mark.unit
def test_canonical_hostnames_map_to_port_7000() -> None:
    entries = {e.id: e for e in build_control_matrix()}
    for entry_id in (
        "edge.route.dataapi-theeyebeta-store",
        "edge.route.dataapiprod-theeyebeta-store",
    ):
        assert entries[entry_id].service_port_dependency == "127.0.0.1:7000"


@pytest.mark.unit
def test_trusted_host_requirements_represented() -> None:
    from control_matrix.expected_registry import TRUSTED_HOST_MATRIX_IDS
    from edge.canonical_routes import CANONICAL_ROUTES

    entries = {e.id: e for e in build_control_matrix()}
    for route in CANONICAL_ROUTES:
        if not route.trusted_host_required:
            continue
        entry_id = TRUSTED_HOST_MATRIX_IDS[route.hostname]
        row = entries[entry_id]
        assert row.trusted_host_dependency is True


@pytest.mark.unit
def test_cloudflare_edge_and_route_registry_exist() -> None:
    ids = _ids(build_control_matrix())
    assert "cloudflare.status.module" in ids
    assert "edge.registry.module" in ids
    assert "edge.data-api.public-routing" in ids


@pytest.mark.unit
def test_future_dynamic_discovery_documented() -> None:
    assert "dynamic" in FUTURE_DYNAMIC_DISCOVERY.lower()


@pytest.mark.unit
def test_matrix_invariants_hold() -> None:
    """Static registry satisfies dangerous-action and backend-only rules."""
    entries = build_control_matrix()
    violations = validate_matrix_invariants(entries)
    assert violations == [], f"Matrix invariant violations: {violations}"


@pytest.mark.unit
def test_required_categories_present() -> None:
    entries = build_control_matrix()
    categories = {e.category for e in entries}
    assert REQUIRED_CATEGORIES <= categories


@pytest.mark.unit
def test_dataapi_hostnames_map_to_port_7000() -> None:
    entries = {e.id: e for e in build_control_matrix()}
    for entry_id in (
        "edge.route.dataapi-theeyebeta-store",
        "edge.route.dataapiprod-theeyebeta-store",
    ):
        row = entries[entry_id]
        assert row.service_port_dependency == "127.0.0.1:7000"
        assert row.health_endpoint == "/health"


@pytest.mark.unit
def test_dataapiprod_notes_shared_backend() -> None:
    entries = {e.id: e for e in build_control_matrix()}
    prod = entries["edge.route.dataapiprod-theeyebeta-store"]
    assert prod.notes is not None
    assert "shared backend" in prod.notes.lower() or "dataapi" in prod.notes.lower()


@pytest.mark.unit
def test_port_9500_not_expected_route_target() -> None:
    entries = build_control_matrix()
    for entry in entries:
        if entry.id == "edge.port.sentinel-unregistered-9500":
            continue
        if entry.service_port_dependency and ":9500" in entry.service_port_dependency:
            pytest.fail(f"{entry.id} must not use port 9500 as expected target")

    sentinel = next(e for e in entries if e.id == "edge.port.sentinel-unregistered-9500")
    assert ":9500" in (sentinel.service_port_dependency or "")
    assert sentinel.backend_only_reason is not None
    assert not sentinel.controllable


@pytest.mark.unit
def test_dangerous_actions_require_audit_and_confirmation() -> None:
    entries = build_control_matrix()
    for entry in entries:
        if not entry.dangerous:
            continue
        assert entry.confirmation_required, f"{entry.id} missing confirmation_required"
        assert entry.audit_required, f"{entry.id} missing audit_required"


@pytest.mark.unit
def test_backend_only_entries_have_reason() -> None:
    entries = build_control_matrix()
    for entry in entries:
        if entry.viewable:
            continue
        assert (
            entry.backend_only_reason or entry.backend_gap or entry.frontend_gap
        ), f"{entry.id} non-viewable without reason/gap"


@pytest.mark.unit
def test_known_admin_routes_represented() -> None:
    ids = _ids(build_control_matrix())
    for entry_id in (
        "admin.page.orders",
        "admin.page.audit",
        "admin.page.agents",
        "admin.page.sql",
        "admin.page.proposals",
        "admin.action.approve-order",
        "master-admin.control-matrix",
    ):
        assert entry_id in ids


@pytest.mark.unit
def test_known_workers_represented() -> None:
    ids = _ids(build_control_matrix())
    for entry_id in (
        "worker.gap-sentinel",
        "worker.macro",
        "worker.massive-ingest",
        "worker.intraday-ingest",
        "worker.backup",
    ):
        assert entry_id in ids


@pytest.mark.unit
def test_known_services_represented() -> None:
    ids = _ids(build_control_matrix())
    for entry_id in (
        "service.systemd.admin-service",
        "service.systemd.data-api",
        "service.systemd.cloudflared",
    ):
        assert entry_id in ids


@pytest.mark.unit
def test_cloudflare_and_edge_categories_exist() -> None:
    entries = build_control_matrix()
    categories = {e.category for e in entries}
    assert "Cloudflare/Edge" in categories
    assert "Edge Route Registry" in categories


@pytest.mark.unit
def test_drift_detection_entries_critical() -> None:
    entries = {e.id: e for e in build_control_matrix()}
    for entry_id in (
        "edge.drift.tunnel-port-mismatch",
        "edge.drift.trusted-host-missing",
        "edge.drift.port-service-mismatch",
    ):
        assert entries[entry_id].priority == "Critical"


@pytest.mark.unit
def test_drift_alerts_surface_critical_cloudflare_drift() -> None:
    alerts = collect_drift_alerts(build_control_matrix())
    assert any("CRITICAL" in a and "9500" in a for a in alerts)
    assert any("TRUSTED_HOSTS" in a for a in alerts)


@pytest.mark.unit
def test_dataapiprod_in_committed_tunnel_config() -> None:
    entries = {e.id: e for e in build_control_matrix()}
    prod = entries["edge.route.dataapiprod-theeyebeta-store"]
    assert prod.backend_gap is None
    assert "cloudflared-config.yml" in prod.backend_source


@pytest.mark.integration
@pytest.mark.asyncio
async def test_control_matrix_api(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/master-admin/control-matrix returns JSON matrix."""
    client, _ = admin_client
    resp = await client.get("/admin/master-admin/control-matrix", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]
    assert len(body["entries"]) > 0
    assert len(body["categories"]) > 0
    ids = {e["id"] for e in body["entries"]}
    assert "edge.route.dataapi-theeyebeta-store" in ids
    assert "edge.route.dataapiprod-theeyebeta-store" in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_master_admin_html_page(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    client, _ = admin_client
    resp = await client.get(
        "/admin/master-admin",
        headers={**auth_headers, "Accept": "text/html"},
    )
    assert resp.status_code == 200
    assert "MASTER_ADMIN control matrix" in resp.text
    assert "dataapi.theeyebeta.store" in resp.text
    assert "dataapiprod.theeyebeta.store" in resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_control_matrix_api_filter_category(
    admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    client, _ = admin_client
    resp = await client.get(
        "/admin/master-admin/control-matrix",
        params={"category": "Cloudflare/Edge"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    entries = resp.json()["entries"]
    assert entries
    assert all(e["category"] == "Cloudflare/Edge" for e in entries)


@pytest.mark.unit
def test_build_control_matrix_response_includes_drift_alerts() -> None:
    payload = build_control_matrix_response()
    assert payload.drift_alerts
    assert payload.generated_at.tzinfo is not None
    assert not any(a.startswith("STALENESS:") for a in payload.drift_alerts)
