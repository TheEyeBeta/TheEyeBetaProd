"""Admin proxy routes for broker-adapter."""

from __future__ import annotations

import httpx
import structlog
from deps import SettingsDep
from fastapi import APIRouter, HTTPException, status
from rbac import Role, require_role

log = structlog.get_logger()

router = APIRouter(prefix="/broker", tags=["broker"])


def register_broker_routes() -> APIRouter:
    """Attach broker status/positions proxy handlers."""

    @router.get("/status", summary="Broker connection status (ANALYST+)")
    async def broker_status(
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.ANALYST),
    ) -> dict:
        """Proxy broker-adapter health."""
        url = f"{settings.broker_adapter_url.rstrip('/')}/health"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="broker-adapter unreachable",
            ) from exc
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        log.info("admin_broker_status", sub=user["sub"])
        return resp.json()

    @router.get("/positions", summary="Broker positions (ANALYST+)")
    async def broker_positions(
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.ANALYST),
    ) -> dict:
        """Proxy Alpaca positions endpoint."""
        url = f"{settings.broker_adapter_url.rstrip('/')}/v1/positions"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="broker-adapter unreachable",
            ) from exc
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        log.info("admin_broker_positions", sub=user["sub"])
        return resp.json()

    return router
