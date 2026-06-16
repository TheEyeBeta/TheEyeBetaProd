"""Admin proxy routes for risk-service."""

from __future__ import annotations

import httpx
import structlog
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, status
from rbac import Role, require_role
from settings import Settings

log = structlog.get_logger()

router = APIRouter(prefix="/risk", tags=["risk"])


async def _risk_get(settings: Settings, path: str) -> dict:
    """GET helper for risk-service HTTP bridge."""
    url = f"{settings.risk_service_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="risk-service unreachable",
        ) from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


def register_risk_routes() -> APIRouter:
    """Attach risk proxy handlers."""

    @router.get("/metrics", summary="Risk metrics (ANALYST+)")
    async def risk_metrics(
        conn: DbConn,
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.ANALYST),
    ) -> dict:
        """Return latest risk metrics from DB or risk-service."""
        rows = await conn.fetch(
            """
            SELECT portfolio_id, metric_name, metric_value, as_of, created_at
              FROM theeyebeta.risk_metrics
             ORDER BY created_at DESC
             LIMIT 50
            """,
        )
        if rows:
            return {
                "source": "database",
                "metrics": [dict(row) for row in rows],
            }
        try:
            data = await _risk_get(settings, "/health")
        except HTTPException:
            return {"source": "unavailable", "metrics": []}
        log.info("admin_risk_metrics", sub=user["sub"], source="risk-service")
        return {"source": "risk-service", "health": data, "metrics": []}

    @router.post("/compute", summary="Trigger risk metrics refresh (OPERATOR+)")
    async def risk_compute(
        settings: SettingsDep,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> dict:
        """Trigger risk-service metrics recomputation."""
        url = f"{settings.risk_service_url.rstrip('/')}/v1/compute-metrics"
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="risk-service unreachable",
            ) from exc
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        log.info("admin_risk_compute", sub=user["sub"])
        return resp.json()

    return router
