"""MASTER_ADMIN DataAPI bridge.

The browser must never receive DataAPI service credentials. This bridge lets a
validated admin-service JWT access DataAPI read surfaces through a server-side
service client.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog
from deps import SettingsDep
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from rbac import Role, require_role
from settings import Settings

log = structlog.get_logger()

router = APIRouter(prefix="/dataapi", tags=["dataapi"])

_TOKEN_CACHE: dict[str, float | str] = {"token": "", "expires_at": 0.0}
_TOKEN_SKEW_SECONDS = 60.0
_TOKEN_TIMEOUT_SECONDS = 20.0
_PROXY_TIMEOUT_SECONDS = 60.0


def _configured(settings: Settings) -> bool:
    return bool(settings.dataapi_client_id.strip() and settings.dataapi_client_secret.strip())


async def _issue_dataapi_token(settings: Settings) -> str:
    """Fetch and cache a scoped DataAPI service JWT."""
    if not _configured(settings):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dataapi_bridge_not_configured",
                    "message": "ADMIN_DATAAPI_CLIENT_ID/SECRET are not configured",
                    "details": {},
                },
            },
        )

    now = time.monotonic()
    cached_token = str(_TOKEN_CACHE.get("token") or "")
    cached_expires_at = float(_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached_token and cached_expires_at > now + _TOKEN_SKEW_SECONDS:
        return cached_token

    token_url = f"{settings.dataapi_url.rstrip('/')}/api/v1/auth/service-token"
    try:
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_SECONDS) as client:
            response = await client.post(
                token_url,
                auth=(settings.dataapi_client_id, settings.dataapi_client_secret),
                json={"requested_scopes": settings.dataapi_scope_list()},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "dataapi_unreachable",
                    "message": "DataAPI service-token endpoint is unreachable",
                    "details": {},
                },
            },
        ) from exc

    if response.status_code >= 400:
        log.warning(
            "admin_dataapi_token_failed",
            status_code=response.status_code,
            body=response.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "code": "dataapi_token_failed",
                    "message": "DataAPI rejected admin bridge service credentials",
                    "details": {"status_code": response.status_code},
                },
            },
        )

    payload = response.json()
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "code": "dataapi_token_missing",
                    "message": "DataAPI service-token response did not include an access token",
                    "details": {},
                },
            },
        )
    expires_minutes = float(payload.get("expires_minutes") or 5)
    _TOKEN_CACHE["token"] = access_token
    _TOKEN_CACHE["expires_at"] = now + max(60.0, expires_minutes * 60.0)
    return access_token


def _validate_proxy_path(path: str) -> str:
    cleaned = path.strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "invalid_dataapi_path",
                    "message": "Invalid DataAPI proxy path",
                    "details": {},
                },
            },
        )
    normalized = "/".join(parts)
    if normalized.startswith("api/v1/auth/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "dataapi_auth_proxy_forbidden",
                    "message": "DataAPI auth endpoints are not exposed through the admin bridge",
                    "details": {},
                },
            },
        )
    return f"/{normalized}"


def _proxy_response(response: httpx.Response) -> Response:
    content_type = response.headers.get("content-type", "application/json")
    if "application/json" in content_type.lower():
        try:
            content: Any = response.json()
        except ValueError:
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=content_type,
            )
        return JSONResponse(content=content, status_code=response.status_code)
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=content_type,
    )


def register_dataapi_routes() -> APIRouter:
    """Attach MASTER_ADMIN DataAPI read proxy handlers."""

    @router.get("/{path:path}", summary="Proxy DataAPI GET request (MASTER_ADMIN)")
    async def proxy_dataapi_get(
        path: str,
        request: Request,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> Response:
        """Proxy DataAPI GET requests with a server-side scoped service token."""
        dataapi_path = _validate_proxy_path(path)
        token = await _issue_dataapi_token(settings)
        url = f"{settings.dataapi_url.rstrip('/')}{dataapi_path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Admin-Actor": user["sub"],
            "X-Request-ID": getattr(request.state, "correlation_id", ""),
        }
        try:
            async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    url,
                    params=request.query_params.multi_items(),
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "code": "dataapi_unreachable",
                        "message": "DataAPI request failed",
                        "details": {"path": dataapi_path},
                    },
                },
            ) from exc

        log.info(
            "admin_dataapi_proxy_get",
            sub=user["sub"],
            path=dataapi_path,
            status_code=response.status_code,
        )
        return _proxy_response(response)

    return router
