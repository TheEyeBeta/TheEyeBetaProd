"""Admin proxy routes for OMS reconciliation."""

from __future__ import annotations

import httpx
import structlog
from audit_log import write_audit_log
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from rbac import Role, require_role

log = structlog.get_logger()

router = APIRouter(prefix="/oms", tags=["oms"])


class ReconciliationResolveRequest(BaseModel):
    """Manual reconciliation drift resolution."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


def register_oms_routes() -> APIRouter:
    """Attach OMS proxy handlers."""

    @router.get("/reconciliation", summary="OMS reconciliation status (OPERATOR+)")
    async def oms_reconciliation(
        settings: SettingsDep,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.OPERATOR),
    ) -> dict:
        """Return OMS health and open reconciliation alerts."""
        url = f"{settings.oms_service_url.rstrip('/')}/health"
        oms_health: dict = {"status": "unavailable"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                oms_health = resp.json()
        except httpx.HTTPError:
            pass

        alerts = await conn.fetch(
            """
            SELECT alert_id, title, message, created_at
              FROM theeyebeta.audit_alerts
             WHERE severity IN ('CRITICAL', 'ESCALATE')
               AND (title ILIKE '%recon%' OR message ILIKE '%reconciliation%')
               AND resolved_at IS NULL
             ORDER BY created_at DESC
             LIMIT 20
            """,
        )
        log.info("admin_oms_reconciliation", sub=user["sub"])
        return {
            "oms": oms_health,
            "open_alerts": [dict(row) for row in alerts],
        }

    @router.post(
        "/reconciliation/resolve",
        summary="Resolve reconciliation drift (MASTER_ADMIN)",
    )
    async def resolve_reconciliation(
        body: ReconciliationResolveRequest,
        settings: SettingsDep,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.MASTER_ADMIN),
    ) -> dict:
        """Proxy reconciliation resolve to OMS with audit record."""
        url = f"{settings.oms_service_url.rstrip('/')}/oms/reconciliation/resolve"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OMS unreachable",
            ) from exc
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        actor = f"admin-api:{user['sub']}"
        await write_audit_log(
            conn,
            actor=actor,
            action="resolve.reconciliation",
            entity_type="oms",
            entity_id="reconciliation",
            payload={"reason": body.reason, "actor": user["sub"]},
        )
        log.info("admin_oms_reconciliation_resolved", sub=user["sub"])
        return resp.json()

    return router
