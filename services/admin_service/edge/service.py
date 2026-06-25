"""Edge Route Registry and Cloudflare status orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from edge.canonical_routes import (
    CANONICAL_ROUTES,
    SHARED_DATAAPI_WARNING,
    UNREGISTERED_INCIDENT_PORTS,
    CanonicalRouteSeed,
)
from edge.cloudflare_client import CloudflareClient, dummy_mode_warning, utc_now
from edge.config_reader import (
    parse_cloudflared_ingress,
    parse_trusted_hosts_from_env,
    parse_tunnel_id,
    read_text_if_exists,
)
from edge.drift_checker import (
    ConfigSnapshot,
    build_drift_alerts,
    compute_route_drift,
    is_drift_critical,
)
from edge.probes import is_port_listening, probe_http_health
from settings import Settings
from zinc_schemas.admin_dto import (
    CloudflareAccessAppsResponse,
    CloudflareAccessStatus,
    CloudflareDnsRoute,
    CloudflareDnsRoutesResponse,
    CloudflareStatusResponse,
    CloudflareTestResponse,
    CloudflareTunnelInfo,
    CloudflareTunnelsResponse,
    CloudflareWafEventsResponse,
    CloudflareWafStatus,
    CloudflareWorkerGatewayStatus,
    EdgeDriftReportResponse,
    EdgePortRegistryEntry,
    EdgePortRegistryResponse,
    EdgeRouteDetailResponse,
    EdgeRouteEntry,
    EdgeRouteListResponse,
    EdgeRoutesCheckResponse,
    EdgeTrustedHostEntry,
    EdgeTrustedHostsResponse,
)

log = structlog.get_logger()


class EdgeRegistryService:
    """Build edge route registry and Cloudflare status from local config + probes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = CloudflareClient(
            api_token=settings.cloudflare_api_token,
            account_id=settings.cloudflare_account_id,
            local_mode=settings.edge_uses_local_mode(),
        )

    @property
    def mode(self) -> str:
        return self._client.mode

    def _load_snapshot(self) -> ConfigSnapshot:
        repo_path = self._settings.edge_cloudflared_repo_config_path()
        host_path = Path(self._settings.edge_cloudflared_host_config)
        runtime_env = self._settings.edge_dataapi_env_path_resolved()
        example_env = self._settings.edge_dataapi_env_example_path_resolved()

        repo_text, repo_status = read_text_if_exists(repo_path)
        host_text, host_status = read_text_if_exists(host_path)
        runtime_text, runtime_status = read_text_if_exists(runtime_env)
        example_text, example_status = read_text_if_exists(example_env)

        repo_routes = parse_cloudflared_ingress(repo_text) if repo_text else {}
        host_routes = parse_cloudflared_ingress(host_text) if host_text else {}
        runtime_hosts = (
            parse_trusted_hosts_from_env(runtime_text) if runtime_text else []
        )
        example_hosts = (
            parse_trusted_hosts_from_env(example_text) if example_text else []
        )

        tunnel_id = parse_tunnel_id(repo_text or host_text or "")
        remote = self._client  # sync placeholder; async fetch in build_routes

        return ConfigSnapshot(
            repo_routes=repo_routes,
            repo_status=repo_status,
            host_routes=host_routes,
            host_status=host_status,
            runtime_trusted_hosts=runtime_hosts,
            runtime_trusted_status=runtime_status,
            repo_example_trusted_hosts=example_hosts,
            remote_routes={},
            remote_status="pending",
        )

    async def _build_route_entry(
        self,
        seed: CanonicalRouteSeed,
        snapshot: ConfigSnapshot,
        remote_routes: dict[str, str],
        remote_status: str,
        checked_at,
    ) -> EdgeRouteEntry:
        repo_target = snapshot.repo_routes.get(seed.hostname)
        host_target = snapshot.host_routes.get(seed.hostname)
        remote_target = remote_routes.get(seed.hostname)
        actual_tunnel = host_target or repo_target

        port_listening, health_probe = await asyncio.gather(
            is_port_listening(
                seed.expected_internal_host,
                seed.expected_internal_port,
                timeout=0.5,
            ),
            probe_http_health(
                seed.expected_internal_host,
                seed.expected_internal_port,
                seed.health_endpoint,
                timeout=1.0,
            ),
        )
        health_status, _ = health_probe

        trusted_present: bool | None = None
        if seed.trusted_host_required:
            if snapshot.runtime_trusted_status == "readable":
                trusted_present = seed.hostname in snapshot.runtime_trusted_hosts
            elif snapshot.repo_example_trusted_hosts:
                trusted_present = seed.hostname in snapshot.repo_example_trusted_hosts

        drift = compute_route_drift(
            seed,
            repo_target=repo_target,
            host_target=host_target,
            remote_target=remote_target,
            port_listening=port_listening,
            health_status=health_status,
            trusted_host_present=trusted_present,
            checked_at=checked_at,
        )

        cf_remote = remote_status
        if remote_target and actual_tunnel and remote_target != actual_tunnel:
            cf_remote = "drift"

        return EdgeRouteEntry(
            hostname=seed.hostname,
            environment=seed.environment,
            expected_internal_host=seed.expected_internal_host,
            expected_internal_port=seed.expected_internal_port,
            actual_tunnel_target=actual_tunnel,
            expected_service_name=seed.expected_service_name,
            systemd_unit=seed.systemd_unit,
            health_endpoint=seed.health_endpoint,
            trusted_host_required=seed.trusted_host_required,
            trusted_host_present=trusted_present,
            repo_config_source=seed.repo_config_source,
            runtime_config_source=str(self._settings.edge_dataapi_env_path_resolved())
            if seed.trusted_host_required
            else str(Path(self._settings.edge_cloudflared_host_config)),
            cloudflare_remote_ingress_status=cf_remote,
            port_listening=port_listening,
            health_status=health_status,
            drift=drift,
            last_checked_at=checked_at,
            owner_module=seed.owner_module,
            notes=seed.notes,
        )

    async def build_routes(self) -> list[EdgeRouteEntry]:
        checked_at = utc_now()
        snapshot = self._load_snapshot()
        repo_path = self._settings.edge_cloudflared_repo_config_path()
        host_path = Path(self._settings.edge_cloudflared_host_config)
        repo_text, _ = read_text_if_exists(repo_path)
        host_text, _ = read_text_if_exists(host_path)
        tunnel_id = parse_tunnel_id(repo_text or host_text or "")
        remote = await self._client.fetch_remote_ingress(tunnel_id)

        entries = await asyncio.gather(
            *[
                self._build_route_entry(
                    seed,
                    snapshot,
                    remote.routes,
                    remote.status,
                    checked_at,
                )
                for seed in CANONICAL_ROUTES
            ],
        )
        return list(entries)

    async def list_routes(self) -> EdgeRouteListResponse:
        routes = await self.build_routes()
        checked_at = utc_now()
        return EdgeRouteListResponse(
            mode=self.mode,
            shared_backend_warning=SHARED_DATAAPI_WARNING,
            routes=routes,
            last_checked_at=checked_at,
        )

    async def get_route(self, hostname: str) -> EdgeRouteDetailResponse | None:
        routes = await self.build_routes()
        for route in routes:
            if route.hostname == hostname:
                return EdgeRouteDetailResponse(route=route)
        return None

    async def drift_report(self) -> EdgeDriftReportResponse:
        routes = await self.build_routes()
        return self.drift_report_for_routes(routes)

    def drift_report_for_routes(
        self,
        routes: list[EdgeRouteEntry],
    ) -> EdgeDriftReportResponse:
        checked_at = utc_now()
        critical = sum(1 for r in routes if is_drift_critical(r.drift))
        drift_count = sum(1 for r in routes if r.drift.status != "ok")
        alerts = build_drift_alerts(routes)
        return EdgeDriftReportResponse(
            mode=self.mode,
            critical_count=critical,
            drift_count=drift_count,
            routes=routes,
            alerts=alerts,
            last_checked_at=checked_at,
        )

    async def port_registry(self) -> EdgePortRegistryResponse:
        checked_at = utc_now()
        seen: dict[int, EdgePortRegistryEntry] = {}
        for seed in CANONICAL_ROUTES:
            listening = await is_port_listening(
                seed.expected_internal_host,
                seed.expected_internal_port,
            )
            seen[seed.expected_internal_port] = EdgePortRegistryEntry(
                port=seed.expected_internal_port,
                host=seed.expected_internal_host,
                service_name=seed.expected_service_name,
                systemd_unit=seed.systemd_unit,
                expected=True,
                listening=listening,
                registered_in_repo=True,
            )
        for port in UNREGISTERED_INCIDENT_PORTS:
            seen[port] = EdgePortRegistryEntry(
                port=port,
                host="127.0.0.1",
                service_name="(unregistered)",
                expected=False,
                listening=await is_port_listening("127.0.0.1", port),
                registered_in_repo=False,
                notes="Incident-class port — tunnel target here indicates Critical drift.",
            )
        return EdgePortRegistryResponse(
            ports=sorted(seen.values(), key=lambda p: p.port),
            unregistered_incident_ports=sorted(UNREGISTERED_INCIDENT_PORTS),
            last_checked_at=checked_at,
        )

    async def trusted_hosts(self) -> EdgeTrustedHostsResponse:
        checked_at = utc_now()
        snapshot = self._load_snapshot()
        runtime = snapshot.runtime_trusted_hosts
        example = snapshot.repo_example_trusted_hosts
        entries: list[EdgeTrustedHostEntry] = []
        for seed in CANONICAL_ROUTES:
            if not seed.trusted_host_required:
                continue
            present_runtime = seed.hostname in runtime if runtime else None
            present_example = seed.hostname in example if example else None
            drift = bool(
                seed.trusted_host_required
                and present_runtime is False
                or (present_example is False and present_runtime is None),
            )
            entries.append(
                EdgeTrustedHostEntry(
                    hostname=seed.hostname,
                    required=True,
                    present_in_runtime=present_runtime,
                    present_in_repo_example=present_example,
                    drift=drift,
                    source_runtime=str(self._settings.edge_dataapi_env_path_resolved()),
                    source_repo_example=str(
                        self._settings.edge_dataapi_env_example_path_resolved(),
                    ),
                ),
            )
        return EdgeTrustedHostsResponse(
            runtime_hosts=runtime,
            repo_example_hosts=example,
            entries=entries,
            last_checked_at=checked_at,
        )

    async def cloudflare_status(
        self,
        routes_for_drift: list[EdgeRouteEntry] | None = None,
    ) -> CloudflareStatusResponse:
        checked_at = utc_now()
        snapshot = self._load_snapshot()
        repo_path = self._settings.edge_cloudflared_repo_config_path()
        host_path = Path(self._settings.edge_cloudflared_host_config)

        repo_text, repo_status = read_text_if_exists(repo_path)
        host_text, host_status = read_text_if_exists(host_path)
        tunnel_id = parse_tunnel_id(repo_text or host_text or "")

        routes = snapshot.host_routes or snapshot.repo_routes
        tunnel_configured = bool(routes) and (
            repo_status == "readable" or host_status == "readable"
        )

        missing: list[str] = []
        if repo_status == "missing":
            missing.append(f"Commit canonical config at {repo_path}")
        if host_status == "missing":
            missing.append(f"Install host tunnel config at {host_path} (sudo fix_tunnel.sh)")
        if self._settings.edge_uses_local_mode():
            missing.append(
                "Set CLOUDFLARE_API_TOKEN + EDGE_MODE=live for remote ingress sync",
            )
        if snapshot.runtime_trusted_status == "missing":
            missing.append("Data API runtime .env not found for TRUSTED_HOSTS parity check")

        origin_targets = sorted(set(routes.values()))
        tunnel_health = "unknown"
        if tunnel_configured:
            drift = (
                self.drift_report_for_routes(routes_for_drift)
                if routes_for_drift is not None
                else await self.drift_report()
            )
            if drift.critical_count:
                tunnel_health = "degraded"
            else:
                tunnel_health = "healthy"

        return CloudflareStatusResponse(
            mode=self.mode,
            cloudflare_configured=tunnel_configured or self._client.credentials_present,
            tunnel_configured=tunnel_configured,
            tunnel_health=tunnel_health,
            public_hostnames=sorted(routes.keys()),
            origin_targets=origin_targets,
            access=CloudflareAccessStatus(
                enabled="unknown" if self._client.local_mode else "unknown",
                detail="Access apps require live Cloudflare API",
            ),
            waf=CloudflareWafStatus(
                status="unknown",
                detail="WAF events require live Cloudflare API",
            ),
            worker_gateway=CloudflareWorkerGatewayStatus(
                status="none",
                detail="No Worker/API gateway registered in repo config.",
            ),
            dns_route_status="degraded" if tunnel_health == "degraded" else "unknown",
            credentials_present=self._client.credentials_present,
            config_sources=[
                str(repo_path),
                str(host_path),
            ],
            last_checked_at=checked_at,
            missing_setup_steps=missing,
            dummy_mode_warning=dummy_mode_warning(self._client.local_mode),
        )

    async def cloudflare_tunnels(self) -> CloudflareTunnelsResponse:
        checked_at = utc_now()
        repo_path = self._settings.edge_cloudflared_repo_config_path()
        host_path = Path(self._settings.edge_cloudflared_host_config)
        repo_text, _ = read_text_if_exists(repo_path)
        host_text, _ = read_text_if_exists(host_path)
        content = repo_text or host_text or ""
        tunnel_id = parse_tunnel_id(content)
        ingress = parse_cloudflared_ingress(content) if content else {}
        drift = await self.drift_report()
        health = "degraded" if drift.critical_count else ("healthy" if ingress else "unknown")
        tunnels = [
            CloudflareTunnelInfo(
                name="my-api",
                tunnel_id=tunnel_id,
                configured=bool(ingress),
                health=health,
                config_source=str(repo_path if repo_text else host_path),
                ingress_hostnames=sorted(ingress.keys()),
            ),
        ]
        return CloudflareTunnelsResponse(
            mode=self.mode,
            tunnels=tunnels,
            last_checked_at=checked_at,
        )

    async def cloudflare_dns_routes(self) -> CloudflareDnsRoutesResponse:
        checked_at = utc_now()
        snapshot = self._load_snapshot()
        repo_path = self._settings.edge_cloudflared_repo_config_path()
        host_path = Path(self._settings.edge_cloudflared_host_config)
        repo_text, _ = read_text_if_exists(repo_path)
        host_text, _ = read_text_if_exists(host_path)
        tunnel_id = parse_tunnel_id(repo_text or host_text or "")
        remote = await self._client.fetch_remote_ingress(tunnel_id)

        hostnames = sorted(
            set(snapshot.repo_routes)
            | set(snapshot.host_routes)
            | set(remote.routes),
        )
        routes: list[CloudflareDnsRoute] = []
        for hostname in hostnames:
            repo_t = snapshot.repo_routes.get(hostname)
            host_t = snapshot.host_routes.get(hostname)
            remote_t = remote.routes.get(hostname)
            drift = bool(
                (repo_t and host_t and repo_t != host_t)
                or (remote_t and host_t and remote_t != host_t)
            )
            routes.append(
                CloudflareDnsRoute(
                    hostname=hostname,
                    origin_target=host_t or repo_t,
                    repo_target=repo_t,
                    host_target=host_t,
                    remote_target=remote_t,
                    drift=drift,
                ),
            )
        return CloudflareDnsRoutesResponse(
            mode=self.mode,
            routes=routes,
            last_checked_at=checked_at,
        )

    async def cloudflare_access_apps(self) -> CloudflareAccessAppsResponse:
        checked_at = utc_now()
        enabled, apps = await self._client.fetch_access_apps()
        return CloudflareAccessAppsResponse(
            mode=self.mode,
            enabled=enabled,
            apps=apps,
            last_checked_at=checked_at,
        )

    async def cloudflare_waf_events(self) -> CloudflareWafEventsResponse:
        checked_at = utc_now()
        events = await self._client.fetch_waf_events()
        return CloudflareWafEventsResponse(
            mode=self.mode,
            events=events,
            last_checked_at=checked_at,
        )

    async def run_cloudflare_test(self) -> CloudflareTestResponse:
        status = await self.cloudflare_status()
        drift = await self.drift_report()
        ok = drift.critical_count == 0
        return CloudflareTestResponse(
            ok=ok,
            mode=self.mode,
            drift_report=drift,
            cloudflare_status=status,
        )

    async def run_routes_check(self) -> EdgeRoutesCheckResponse:
        drift = await self.drift_report()
        routes = await self.list_routes()
        ok = drift.critical_count == 0
        return EdgeRoutesCheckResponse(ok=ok, drift_report=drift, routes=routes)
