"""Admin proxy routes for compliance-service."""

from __future__ import annotations

import structlog
from deps import DbConn
from fastapi import APIRouter
from rbac import Role, require_role

log = structlog.get_logger()

router = APIRouter(prefix="/compliance", tags=["compliance"])


def register_compliance_routes() -> APIRouter:
    """Attach compliance read handlers."""

    @router.get("/checks", summary="Compliance check log (COMPLIANCE+)")
    async def compliance_checks(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.COMPLIANCE),
    ) -> dict:
        """Return recent compliance check rows."""
        rows = await conn.fetch(
            """
            SELECT check_id, order_id, rule_id, outcome, detail, created_at
              FROM theeyebeta.compliance_checks
             ORDER BY created_at DESC
             LIMIT 100
            """,
        )
        log.info("admin_compliance_checks", count=len(rows), sub=user["sub"])
        return {"checks": [dict(row) for row in rows], "total": len(rows)}

    return router
