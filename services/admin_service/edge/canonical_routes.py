"""Canonical edge route seeds — source of truth for expected public hostnames."""

from __future__ import annotations

from dataclasses import dataclass

SHARED_DATAAPI_WARNING = (
    "dataapi.theeyebeta.store and dataapiprod.theeyebeta.store currently route to "
    "the same Data API service on port 7000. This is valid only if shared backend "
    "is intentional."
)

UNREGISTERED_INCIDENT_PORTS: frozenset[int] = frozenset({9500})


@dataclass(frozen=True, slots=True)
class CanonicalRouteSeed:
    """Expected production edge route definition."""

    hostname: str
    environment: str
    expected_internal_host: str
    expected_internal_port: int
    expected_service_name: str
    systemd_unit: str | None
    health_endpoint: str
    trusted_host_required: bool
    trusted_host_hostnames: tuple[str, ...]
    owner_module: str
    repo_config_source: str
    notes: str | None = None


CANONICAL_ROUTES: tuple[CanonicalRouteSeed, ...] = (
    CanonicalRouteSeed(
        hostname="dataapi.theeyebeta.store",
        environment="prod",
        expected_internal_host="127.0.0.1",
        expected_internal_port=7000,
        expected_service_name="data-api",
        systemd_unit="theeyebeta-dataapi",
        health_endpoint="/health",
        trusted_host_required=True,
        trusted_host_hostnames=("dataapi.theeyebeta.store", "api.theeyebeta.store"),
        owner_module="Data API",
        repo_config_source="TheEyeBetaDataAPI/TheEyeBetaDataAPI/deploy/cloudflared-config.yml",
    ),
    CanonicalRouteSeed(
        hostname="dataapiprod.theeyebeta.store",
        environment="shared",
        expected_internal_host="127.0.0.1",
        expected_internal_port=7000,
        expected_service_name="data-api",
        systemd_unit="theeyebeta-dataapi",
        health_endpoint="/health",
        trusted_host_required=True,
        trusted_host_hostnames=("dataapiprod.theeyebeta.store",),
        owner_module="Data API",
        repo_config_source="TheEyeBetaDataAPI/TheEyeBetaDataAPI/deploy/cloudflared-config.yml",
        notes="Shared backend with dataapi.theeyebeta.store on :7000.",
    ),
    CanonicalRouteSeed(
        hostname="api.theeyebeta.store",
        environment="prod",
        expected_internal_host="127.0.0.1",
        expected_internal_port=8000,
        expected_service_name="local-api",
        systemd_unit="theeyebeta-api",
        health_endpoint="/health",
        trusted_host_required=False,
        trusted_host_hostnames=(),
        owner_module="TheEyeBetaLocal Main API",
        repo_config_source="TheEyeBetaDataAPI/TheEyeBetaDataAPI/deploy/cloudflared-config.yml",
    ),
    CanonicalRouteSeed(
        hostname="admin.theeyebeta.store",
        environment="prod",
        expected_internal_host="127.0.0.1",
        expected_internal_port=7200,
        expected_service_name="admin-service",
        systemd_unit="theeyebeta-admin",
        health_endpoint="/admin/health",
        trusted_host_required=False,
        trusted_host_hostnames=(),
        owner_module="The Eye Terminal",
        repo_config_source="TheEyeBetaDataAPI/TheEyeBetaDataAPI/deploy/cloudflared-config.yml",
    ),
)
