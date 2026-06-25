"""Authenticated HTTP bridge to TheEyeBetaDataAPI."""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from settings import Settings

log = structlog.get_logger()

_TOKEN_SKEW_SECONDS = 30


class DataApiBridge:
    """Service-token client for Data API routes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def base_url(self) -> str:
        return self._settings.dataapi_bridge_base_url()

    def configured(self) -> bool:
        return bool(self.base_url) and self._settings.dataapi_credentials_present()

    async def get_access_token(self, *, scopes: list[str] | None = None) -> str:
        """Return a cached service JWT, refreshing when near expiry."""
        now = time.time()
        if self._token and now < self._token_expires_at - _TOKEN_SKEW_SECONDS:
            return self._token

        requested = scopes or self._settings.dataapi_scopes_list()
        client_id = self._settings.admin_dataapi_client_id.strip()
        secret = self._settings.admin_dataapi_client_secret.strip()
        if not client_id or not secret:
            msg = "Data API client credentials are not configured"
            raise RuntimeError(msg)

        url = f"{self.base_url}/api/v1/auth/service-token"
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=self._settings.admin_dataapi_verify_ssl,
        ) as client:
            response = await client.post(
                url,
                json={"requested_scopes": requested},
                auth=(client_id, secret),
            )
            response.raise_for_status()
            payload = response.json()

        token = str(payload["access_token"])
        expires_minutes = int(payload.get("expires_minutes") or 60)
        self._token = token
        self._token_expires_at = now + expires_minutes * 60
        log.info("dataapi_service_token_issued", scopes=payload.get("scopes"))
        return token

    async def get_json(
        self,
        path: str,
        *,
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """GET a JSON endpoint with bearer auth."""
        token = await self.get_access_token(scopes=scopes)
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=self._settings.admin_dataapi_verify_ssl,
        ) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            body = response.json()
        return dict(body) if isinstance(body, dict) else {"data": body}


async def fetch_dataapi_health(settings: Settings) -> dict[str, Any]:
    """Public health probe (no auth) against the configured bridge URL."""
    base = settings.dataapi_bridge_base_url()
    if not base:
        return {"status": "unconfigured", "reachable": False}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{base}/health")
        response.raise_for_status()
        body = response.json()
    return {
        "status": str(body.get("status") or "unknown"),
        "reachable": True,
        "base_url": base,
        "body": body,
    }


async def fetch_market_quotes(settings: Settings, symbols: list[str]) -> dict[str, Any]:
    """Fetch live quotes from Data API (market:read scope)."""
    if not symbols:
        return {"quotes": [], "error": "no_symbols", "configured": settings.dataapi_credentials_present()}
    bridge = DataApiBridge(settings)
    if not bridge.configured():
        return {"quotes": [], "error": "unconfigured", "configured": False}
    joined = ",".join(symbols)
    try:
        payload = await bridge.get_json(
            f"/api/v1/market-data/quotes?symbols={joined}",
            scopes=["market:read"],
        )
        return {
            "quotes": payload.get("quotes") or [],
            "error": None,
            "configured": True,
            "symbols": symbols,
        }
    except httpx.HTTPError as exc:
        log.warning("dataapi_quotes_failed", error=str(exc)[:200])
        return {"quotes": [], "error": str(exc)[:200], "configured": True, "symbols": symbols}
