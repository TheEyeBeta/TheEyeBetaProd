"""Admin services API — Docker container status + whitelisted restart."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, DockerDep
from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from fastapi import APIRouter, HTTPException, Request, status
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    RestartServiceRequest,
    RestartServiceResponse,
    ServiceStatusEntry,
    ServiceStatusResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/services", tags=["services"])

NETWORK_NAME = "theeyebeta-net"

# Whitelist of 16 services (mirrors ``services/<dir>`` → kebab-case).
RESTARTABLE_SERVICES: frozenset[str] = frozenset(
    {
        "admin-service",
        "agent-runtime",
        "api",
        "audit-service",
        "backtest-engine",
        "broker-adapter-alpaca",
        "compliance-service",
        "data-ingestion",
        "guard-service",
        "llm-gateway",
        "master-orchestrator",
        "oms",
        "risk-service",
        "rnd-agent",
        "snapshot-packager",
        "worker",
    },
)


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


def _parse_started_at(raw: str | None) -> datetime | None:
    """Parse Docker ``State.StartedAt`` ISO-8601 timestamp.

    Args:
        raw: Value from ``container.attrs['State']['StartedAt']`` (may be the
            zero sentinel ``0001-01-01T00:00:00Z``).

    Returns:
        Timezone-aware UTC datetime, or ``None`` when unavailable / zero.
    """
    if not raw:
        return None
    if raw.startswith("0001-"):
        return None
    cleaned = raw
    # Docker emits nanoseconds; truncate to microseconds for fromisoformat.
    if "." in cleaned and cleaned.endswith("Z"):
        head, _, tail = cleaned.partition(".")
        frac = tail[:-1][:6]
        cleaned = f"{head}.{frac}+00:00"
    elif cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _container_to_entry(container: Container) -> ServiceStatusEntry:
    """Map a docker-py ``Container`` to :class:`ServiceStatusEntry`."""
    attrs: dict[str, Any] = container.attrs or {}
    state: dict[str, Any] = attrs.get("State", {}) or {}
    config: dict[str, Any] = attrs.get("Config", {}) or {}
    health = state.get("Health") or {}
    health_status = str(health.get("Status")) if isinstance(health, dict) and health else None

    started_at = _parse_started_at(state.get("StartedAt"))
    uptime: int | None = None
    if started_at is not None and state.get("Running"):
        uptime = max(0, int((datetime.now(tz=UTC) - started_at).total_seconds()))

    image = config.get("Image") or attrs.get("Image") or ""
    name = container.name or attrs.get("Name", "").lstrip("/")

    return ServiceStatusEntry(
        name=name,
        image=str(image),
        state=str(state.get("Status") or "unknown"),
        health=health_status,
        started_at=started_at,
        uptime_seconds=uptime,
        container_id=str(container.id or attrs.get("Id", "")),
    )


def _list_network_containers(docker_client: DockerClient) -> list[Container]:
    """Return containers attached to :data:`NETWORK_NAME` (sync docker-py).

    Falls back to ``containers.list`` when the network is missing so the
    endpoint stays usable in environments where the compose stack hasn't
    started yet.
    """
    try:
        network = docker_client.networks.get(NETWORK_NAME)
    except NotFound:
        return list(docker_client.containers.list(all=True))
    network.reload()
    container_ids = list((network.attrs or {}).get("Containers", {}) or {})
    out: list[Container] = []
    for cid in container_ids:
        try:
            out.append(docker_client.containers.get(cid))
        except NotFound:
            continue
    return out


def _find_container(docker_client: DockerClient, name: str) -> Container | None:
    """Locate a container by exact name or compose-style suffix match."""
    try:
        return docker_client.containers.get(name)
    except NotFound:
        pass
    for container in docker_client.containers.list(all=True):
        cname = (container.name or "").lstrip("/")
        if cname == name or cname.endswith(f"-{name}-1") or cname.endswith(f"_{name}_1"):
            return container
    return None


def register_services_routes(limiter: Limiter) -> APIRouter:
    """Attach Docker status + restart handlers (POST is rate-limited)."""

    @router.get("/status", response_model=ServiceStatusResponse)
    async def list_service_status(
        user: CurrentUser,
        docker_client: DockerDep,
    ) -> ServiceStatusResponse:
        """Return Docker containers on ``theeyebeta-net`` with health/uptime."""
        try:
            containers = await asyncio.to_thread(_list_network_containers, docker_client)
        except APIError as exc:
            log.error("admin_services_status_failed", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Docker daemon error",
            ) from exc

        entries = [_container_to_entry(c) for c in containers]
        log.info(
            "admin_services_status_listed",
            count=len(entries),
            sub=user["sub"],
        )
        return ServiceStatusResponse(services=entries, network=NETWORK_NAME)

    @router.post("/{name}/restart", response_model=RestartServiceResponse)
    @limiter.limit("20/minute")
    async def restart_service(
        request: Request,  # noqa: ARG001 — required by slowapi
        name: str,
        body: RestartServiceRequest,
        user: CurrentUser,
        conn: DbConn,
        docker_client: DockerDep,
    ) -> RestartServiceResponse:
        """Restart a whitelisted container and audit-log the action."""
        if name not in RESTARTABLE_SERVICES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Service '{name}' is not in the restart whitelist",
            )

        actor = _actor(user)
        audit_payload = body.model_dump(mode="json")

        container = await asyncio.to_thread(_find_container, docker_client, name)
        if container is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Container for service '{name}' not found",
            )

        try:
            await asyncio.to_thread(container.restart, timeout=body.timeout_seconds)
        except APIError as exc:
            log.error(
                "admin_service_restart_failed",
                service=name,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Docker refused to restart '{name}': {exc}",
            ) from exc

        await asyncio.to_thread(container.reload)
        new_state = str(((container.attrs or {}).get("State") or {}).get("Status") or "unknown")

        await write_audit_log(
            conn,
            actor=actor,
            action="restart.service",
            entity_type="service",
            entity_id=name,
            payload={**audit_payload, "container_id": container.id},
        )

        log.info(
            "admin_service_restarted",
            service=name,
            container_id=container.id,
            sub=user["sub"],
        )
        return RestartServiceResponse(
            name=name,
            container_id=str(container.id or ""),
            restarted=True,
            state=new_state,
        )

    return router
