"""Allowlisted systemd services with port and hostname ownership."""

from __future__ import annotations

from dataclasses import dataclass

from edge.canonical_routes import CANONICAL_ROUTES


def _hostnames_for_service(service_key: str) -> tuple[str, ...]:
    return tuple(
        route.hostname
        for route in CANONICAL_ROUTES
        if route.expected_service_name == service_key
    )


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """One allowlisted systemd service in the Terminal registry."""

    key: str
    title: str
    systemd_unit: str
    unit_file: str
    port: int | None
    hostnames: tuple[str, ...]
    health_endpoint: str | None
    dependencies: tuple[str, ...]
    critical: bool = False
    supports_restart: bool = True
    supports_start: bool = True
    supports_stop: bool = True
    supports_enable: bool = True
    supports_disable: bool = True
    priority: str = "Medium"


CANONICAL_SERVICES: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        key="admin-service",
        title="Admin Terminal",
        systemd_unit="theeyebeta-admin",
        unit_file="TheEyeProd/infra/systemd/theeyebeta-admin.service",
        port=7200,
        hostnames=_hostnames_for_service("admin-service"),
        health_endpoint="/admin/health",
        dependencies=("postgresql", "redis"),
        critical=True,
        priority="High",
    ),
    ServiceDefinition(
        key="data-api",
        title="Data API",
        systemd_unit="theeyebeta-dataapi",
        unit_file="TheEyeBetaDataAPI/scripts/install_service.sh",
        port=7000,
        hostnames=(
            "dataapi.theeyebeta.store",
            "dataapiprod.theeyebeta.store",
        ),
        health_endpoint="/health",
        dependencies=("postgresql",),
        critical=True,
        priority="Critical",
    ),
    ServiceDefinition(
        key="local-api",
        title="TheEyeBeta Local API",
        systemd_unit="theeyebeta-api",
        unit_file="TheEyeBetaLocal/scripts/systemd/theeyebeta-api.service",
        port=8000,
        hostnames=_hostnames_for_service("local-api"),
        health_endpoint="/health",
        dependencies=("postgresql", "nats"),
        critical=False,
    ),
    ServiceDefinition(
        key="local-engine",
        title="TheEyeBeta Engine",
        systemd_unit="theeyebeta-engine",
        unit_file="TheEyeBetaLocal/scripts/systemd/theeyebeta-engine.service",
        port=None,
        hostnames=(),
        health_endpoint=None,
        dependencies=("postgresql", "nats"),
        critical=False,
        supports_stop=False,
    ),
    ServiceDefinition(
        key="local-trask",
        title="Trask orchestrator",
        systemd_unit="theeyebeta-trask",
        unit_file="TheEyeBetaLocal/scripts/systemd/theeyebeta-trask.service",
        port=8090,
        hostnames=(),
        health_endpoint="/health",
        dependencies=("postgresql",),
        critical=False,
    ),
    ServiceDefinition(
        key="llm-gateway",
        title="LiteLLM gateway",
        systemd_unit="theeyebeta-litellm",
        unit_file="infra/systemd/theeyebeta-litellm.service",
        port=7020,
        hostnames=(),
        health_endpoint="/health",
        dependencies=(),
        critical=False,
    ),
    ServiceDefinition(
        key="nats",
        title="NATS messaging",
        systemd_unit="nats",
        unit_file="Infrastructure package unit",
        port=4222,
        hostnames=(),
        health_endpoint=None,
        dependencies=(),
        critical=True,
        supports_restart=False,
        supports_stop=False,
        supports_disable=False,
    ),
    ServiceDefinition(
        key="redis",
        title="Redis cache",
        systemd_unit="redis-server",
        unit_file="Infrastructure package unit",
        port=6379,
        hostnames=(),
        health_endpoint=None,
        dependencies=(),
        critical=True,
        supports_restart=False,
        supports_stop=False,
        supports_disable=False,
    ),
    ServiceDefinition(
        key="cloudflared",
        title="Cloudflare tunnel",
        systemd_unit="cloudflared",
        unit_file="/etc/cloudflared/config.yml",
        port=None,
        hostnames=tuple(route.hostname for route in CANONICAL_ROUTES),
        health_endpoint=None,
        dependencies=(),
        critical=True,
        supports_restart=True,
        supports_stop=True,
        supports_disable=True,
        priority="Critical",
    ),
)

_SERVICES_BY_KEY = {service.key: service for service in CANONICAL_SERVICES}
_ALLOWED_UNITS = frozenset(service.systemd_unit for service in CANONICAL_SERVICES)
_CRITICAL_KEYS = frozenset(service.key for service in CANONICAL_SERVICES if service.critical)


def service_by_key(key: str) -> ServiceDefinition | None:
    return _SERVICES_BY_KEY.get(key)


def all_service_keys() -> tuple[str, ...]:
    return tuple(_SERVICES_BY_KEY.keys())


def allowed_systemd_units() -> frozenset[str]:
    return _ALLOWED_UNITS


def is_critical_service(key: str) -> bool:
    return key in _CRITICAL_KEYS


def expected_ports() -> dict[int, str]:
    """Map registered expected ports to service keys (excludes 9500)."""
    ports: dict[int, str] = {}
    for service in CANONICAL_SERVICES:
        if service.port is not None:
            ports[service.port] = service.key
    return ports
