"""Services / systemd control plane orchestration."""

from __future__ import annotations

from typing import Any

import structlog
from audit_log import write_audit_log
from edge.canonical_routes import UNREGISTERED_INCIDENT_PORTS
from edge.probes import is_port_listening, probe_http_health
from services_control.registry import (
    CANONICAL_SERVICES,
    ServiceDefinition,
    allowed_systemd_units,
    expected_ports,
    service_by_key,
)
from services_control.repository import ServicesRepository
from services_control.systemd_probe import AllowlistedSystemdProbe, SystemdUnitStatus
from settings import Settings
from zinc_schemas.admin_dto import (
    ServiceActionResponse,
    ServiceDetailResponse,
    ServiceHistoryEntry,
    ServiceHistoryResponse,
    ServiceListResponse,
    ServiceLogLine,
    ServiceLogsResponse,
    ServicePortEntry,
    ServicePortRegistryResponse,
    ServiceRegistryEntry,
    ServiceStatusEntry,
    ServiceStatusResponse,
)

log = structlog.get_logger()


class ServicesControlService:
    """Allowlisted systemd visibility, port ownership, and audited mutations."""

    def __init__(
        self,
        conn: Any,
        settings: Settings,
        *,
        probe: AllowlistedSystemdProbe | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = ServicesRepository(conn)
        self._probe = probe or AllowlistedSystemdProbe(
            allowed_units=allowed_systemd_units(),
            enabled=settings.services_systemd_enabled(),
        )

    @property
    def mode(self) -> str:
        return "live" if self._probe.available else "local"

    async def _port_listening(self, service: ServiceDefinition) -> bool | None:
        if service.port is None:
            return None
        if self._settings.services_uses_local_mode():
            return None
        return await is_port_listening("127.0.0.1", service.port)

    async def _health_probe(self, service: ServiceDefinition) -> tuple[str | None, str | None]:
        if service.port is None or not service.health_endpoint:
            return None, None
        if self._settings.services_uses_local_mode():
            return None, None
        label, _ = await probe_http_health(
            "127.0.0.1",
            service.port,
            service.health_endpoint,
        )
        return label, service.health_endpoint

    def _health_label(self, status: SystemdUnitStatus) -> str:
        if status.active_state == "active":
            return "healthy"
        if status.active_state in {"inactive", "failed", "dead"}:
            return "unhealthy"
        return "unknown"

    async def _build_entry(
        self,
        service: ServiceDefinition,
        *,
        status: SystemdUnitStatus,
        last_action: dict[str, Any] | None,
    ) -> ServiceRegistryEntry:
        listening = await self._port_listening(service)
        health_status, health_endpoint = await self._health_probe(service)
        return ServiceRegistryEntry(
            name=service.key,
            title=service.title,
            systemd_unit=service.systemd_unit,
            unit_file=service.unit_file,
            status=f"{status.active_state} ({status.sub_state})",
            health=self._health_label(status),
            health_probe=health_status,
            uptime_seconds=status.uptime_seconds,
            restart_count=status.n_restarts,
            memory_bytes=status.memory_bytes,
            cpu_usage_nsec=status.cpu_nsec,
            listening_port=service.port,
            port_listening=listening,
            public_hostnames=list(service.hostnames),
            health_endpoint=health_endpoint or service.health_endpoint,
            dependencies=list(service.dependencies),
            enabled=status.enabled,
            critical=service.critical,
            supports_restart=service.supports_restart,
            supports_start=service.supports_start,
            supports_stop=service.supports_stop,
            supports_enable=service.supports_enable,
            supports_disable=service.supports_disable,
            started_at=status.started_at,
            last_operator_action=self._history_entry(last_action),
            priority=service.priority,
        )

    @staticmethod
    def _history_entry(row: dict[str, Any] | None) -> ServiceHistoryEntry | None:
        if not row:
            return None
        return ServiceHistoryEntry(
            id=int(row["id"]),
            service_name=str(row["service_name"]),
            action=str(row["action"]),
            actor=str(row["actor"]),
            reason=str(row.get("reason") or ""),
            status=str(row["status"]),
            message=str(row.get("message") or ""),
            created_at=row["created_at"],
        )

    async def list_services(self) -> ServiceListResponse:
        entries: list[ServiceRegistryEntry] = []
        for service in CANONICAL_SERVICES:
            status = await self._probe.show(service.systemd_unit)
            last_action = await self._repo.last_action(service.key)
            entries.append(
                await self._build_entry(service, status=status, last_action=last_action),
            )
        return ServiceListResponse(
            mode=self.mode,
            services=entries,
            checked_at=ServicesRepository.utc_now(),
        )

    async def get_service(self, name: str) -> ServiceDetailResponse | None:
        service = service_by_key(name)
        if service is None:
            return None
        status = await self._probe.show(service.systemd_unit)
        last_action = await self._repo.last_action(service.key)
        entry = await self._build_entry(service, status=status, last_action=last_action)
        history_rows = await self._repo.list_history(service.key, limit=25)
        logs = await self._probe.journal(service.systemd_unit)
        return ServiceDetailResponse(
            **entry.model_dump(),
            recent_logs=[
                ServiceLogLine(line=line, source="journal") for line in logs[:20]
            ],
            history=[self._history_entry(row) for row in history_rows if self._history_entry(row)],
        )

    async def legacy_status_response(self) -> ServiceStatusResponse:
        """Backward-compatible payload for ``GET /admin/services/status``."""
        listing = await self.list_services()
        services = [
            ServiceStatusEntry(
                name=entry.name,
                image=entry.systemd_unit,
                state=entry.status,
                health=entry.health,
                started_at=entry.started_at,
                uptime_seconds=entry.uptime_seconds,
                container_id=entry.systemd_unit,
            )
            for entry in listing.services
        ]
        return ServiceStatusResponse(services=services, network="systemd")

    async def port_registry(self) -> ServicePortRegistryResponse:
        ports: list[ServicePortEntry] = []
        registered = expected_ports()
        seen: set[int] = set()
        for service in CANONICAL_SERVICES:
            if service.port is None or service.port in seen:
                continue
            seen.add(service.port)
            listening = await is_port_listening("127.0.0.1", service.port)
            ports.append(
                ServicePortEntry(
                    port=service.port,
                    host="127.0.0.1",
                    service_name=service.key,
                    systemd_unit=service.systemd_unit,
                    public_hostnames=list(service.hostnames),
                    health_endpoint=service.health_endpoint,
                    expected=True,
                    listening=listening,
                ),
            )
        for port in sorted(UNREGISTERED_INCIDENT_PORTS):
            ports.append(
                ServicePortEntry(
                    port=port,
                    host="127.0.0.1",
                    service_name="(unregistered)",
                    systemd_unit=None,
                    public_hostnames=[],
                    health_endpoint=None,
                    expected=False,
                    listening=await is_port_listening("127.0.0.1", port),
                    notes="Incident-class port — not an expected service target.",
                ),
            )
        ports.sort(key=lambda row: row.port)
        return ServicePortRegistryResponse(
            ports=ports,
            unregistered_incident_ports=sorted(UNREGISTERED_INCIDENT_PORTS),
            checked_at=ServicesRepository.utc_now(),
        )

    async def get_logs(self, name: str) -> ServiceLogsResponse | None:
        service = service_by_key(name)
        if service is None:
            return None
        lines = await self._probe.journal(service.systemd_unit)
        return ServiceLogsResponse(
            name=name,
            lines=[ServiceLogLine(line=line, source="journal") for line in lines],
            bounded=True,
            journal_available=self._probe.available,
        )

    async def get_history(self, name: str, *, limit: int = 50) -> ServiceHistoryResponse | None:
        service = service_by_key(name)
        if service is None:
            return None
        rows = await self._repo.list_history(service.key, limit=limit)
        return ServiceHistoryResponse(
            name=name,
            entries=[entry for row in rows if (entry := self._history_entry(row))],
        )

    async def _audit(
        self,
        *,
        actor: str,
        action: str,
        service_name: str,
        payload: dict[str, Any],
    ) -> None:
        await write_audit_log(
            self._conn,
            actor=actor,
            action=action,
            entity_type="service",
            entity_id=service_name,
            payload=payload,
        )

    async def _mutate(
        self,
        name: str,
        action: str,
        *,
        actor: str,
        reason: str,
        runner: Any,
    ) -> ServiceActionResponse | None:
        service = service_by_key(name)
        if service is None:
            return None
        capability = {
            "restart": service.supports_restart,
            "start": service.supports_start,
            "stop": service.supports_stop,
            "enable": service.supports_enable,
            "disable": service.supports_disable,
        }.get(action)
        if not capability:
            return None
        try:
            result = await runner(service.systemd_unit)
        except ValueError as exc:
            return ServiceActionResponse(
                name=name,
                action=action,
                status="rejected",
                message=str(exc),
                audited=False,
                systemd_unit=service.systemd_unit,
                reason=reason,
            )
        if result.attempted and result.success:
            status_label = "ok"
        elif not result.attempted:
            status_label = "recorded"
        else:
            status_label = "failed"
        await self._repo.record_action(
            service_name=name,
            action=action,
            actor=actor,
            reason=reason,
            status=status_label,
            message=result.message,
        )
        await self._audit(
            actor=actor,
            action=f"services.{action}",
            service_name=name,
            payload={
                "reason": reason,
                "unit": service.systemd_unit,
                "systemd": result.message,
                "critical": service.critical,
            },
        )
        return ServiceActionResponse(
            name=name,
            action=action,
            status=status_label,
            message=result.message,
            audited=True,
            systemd_unit=service.systemd_unit,
            reason=reason,
        )

    async def restart(self, name: str, *, actor: str, reason: str) -> ServiceActionResponse | None:
        return await self._mutate(
            name,
            "restart",
            actor=actor,
            reason=reason,
            runner=self._probe.restart,
        )

    async def start(self, name: str, *, actor: str, reason: str) -> ServiceActionResponse | None:
        return await self._mutate(name, "start", actor=actor, reason=reason, runner=self._probe.start)

    async def stop(self, name: str, *, actor: str, reason: str) -> ServiceActionResponse | None:
        return await self._mutate(name, "stop", actor=actor, reason=reason, runner=self._probe.stop)

    async def enable(self, name: str, *, actor: str, reason: str) -> ServiceActionResponse | None:
        return await self._mutate(
            name,
            "enable",
            actor=actor,
            reason=reason,
            runner=self._probe.enable,
        )

    async def disable(self, name: str, *, actor: str, reason: str) -> ServiceActionResponse | None:
        return await self._mutate(
            name,
            "disable",
            actor=actor,
            reason=reason,
            runner=self._probe.disable,
        )
