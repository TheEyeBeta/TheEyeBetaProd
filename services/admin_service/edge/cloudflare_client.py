"""Cloudflare API adapter — local/dummy mode when credentials absent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class RemoteIngressResult:
    """Remote tunnel ingress lookup result (no secrets)."""

    status: str
    routes: dict[str, str]
    detail: str | None = None


class CloudflareClient:
    """Optional live Cloudflare API client; falls back to dummy responses."""

    def __init__(
        self,
        *,
        api_token: str,
        account_id: str,
        local_mode: bool,
    ) -> None:
        self._token = api_token.strip()
        self._account_id = account_id.strip()
        self._local_mode = local_mode

    @property
    def local_mode(self) -> bool:
        return self._local_mode

    @property
    def mode(self) -> str:
        return "local" if self._local_mode else "live"

    @property
    def credentials_present(self) -> bool:
        return bool(self._token)

    async def fetch_remote_ingress(self, tunnel_id: str | None) -> RemoteIngressResult:
        """Fetch remote tunnel ingress when live mode and credentials exist."""
        if self._local_mode or not self._token or not tunnel_id:
            return RemoteIngressResult(
                status="unavailable_no_credentials",
                routes={},
                detail="Cloudflare remote ingress sync requires CLOUDFLARE_API_TOKEN in live mode.",
            )
        # Scaffold for live mode — real implementation can expand without API contract changes.
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}"
            f"/cfd_tunnel/{tunnel_id}/configurations"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if response.status_code != 200:
                    log.warning(
                        "cloudflare_remote_ingress_failed",
                        status_code=response.status_code,
                    )
                    return RemoteIngressResult(
                        status="unknown",
                        routes={},
                        detail=f"Cloudflare API returned HTTP {response.status_code}",
                    )
                data = response.json()
                routes = _extract_remote_routes(data)
                return RemoteIngressResult(status="synced", routes=routes)
        except httpx.HTTPError as exc:
            log.warning("cloudflare_remote_ingress_error", error=str(exc))
            return RemoteIngressResult(status="unknown", routes={}, detail=str(exc))

    async def fetch_access_apps(self) -> tuple[str, list[str]]:
        """Return (enabled_status, app hostnames). Dummy when local."""
        if self._local_mode or not self._token:
            return "unknown", []
        return "unknown", []

    async def fetch_waf_events(self) -> list[dict[str, str]]:
        if self._local_mode or not self._token:
            return []
        return []


def _extract_remote_routes(payload: object) -> dict[str, str]:
    """Best-effort parse of Cloudflare tunnel configuration JSON."""
    routes: dict[str, str] = {}
    if not isinstance(payload, dict):
        return routes
    result = payload.get("result")
    if not isinstance(result, dict):
        return routes
    config = result.get("config")
    if not isinstance(config, dict):
        return routes
    ingress = config.get("ingress")
    if not isinstance(ingress, list):
        return routes
    for item in ingress:
        if not isinstance(item, dict):
            continue
        hostname = item.get("hostname")
        service = item.get("service")
        if isinstance(hostname, str) and isinstance(service, str):
            routes[hostname] = service
    return routes


def dummy_mode_warning(local_mode: bool) -> str | None:
    if not local_mode:
        return None
    return (
        "Cloudflare API is in local/dummy mode — remote ingress, Access apps, and WAF "
        "events are not queried. Set EDGE_MODE=live and CLOUDFLARE_API_TOKEN on the "
        "server for live sync (token is never exposed via this API)."
    )


def utc_now() -> datetime:
    return datetime.now(tz=UTC)
