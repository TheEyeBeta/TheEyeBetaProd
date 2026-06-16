"""Admin guard API — guardrail violation viewer + resolve action."""

from __future__ import annotations

import json
from typing import Any

import asyncpg
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn
from fastapi import APIRouter, HTTPException, Query, Request, status
from rbac import Role, require_role
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    GuardViolationEntry,
    GuardViolationsResponse,
    ResolveGuardViolationRequest,
    ResolveGuardViolationResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/guard", tags=["guard"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_VALID_SEVERITIES = ("low", "medium", "high", "critical")


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


def _parse_detail(raw: object) -> dict[str, Any]:
    """Normalize ``guard_violations.detail`` from asyncpg."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _row_to_entry(row: asyncpg.Record) -> GuardViolationEntry:
    """Map a DB row to :class:`GuardViolationEntry`."""
    return GuardViolationEntry(
        id=int(row["id"]),
        ts=row["ts"],
        run_id=row["run_id"],
        agent_id=row["agent_id"],
        violation_type=row["violation_type"],
        severity=row["severity"],
        detail=_parse_detail(row["detail"]),
        resolution=row["resolution"],
        resolved=bool(row["resolved"]),
        resolved_by=row["resolved_by"],
        resolved_at=row["resolved_at"],
        resolution_note=row["resolution_note"],
    )


VALID_SEVERITIES: tuple[str, ...] = _VALID_SEVERITIES


def validate_severity(severity: str | None) -> None:
    """Raise 422 unless ``severity`` is ``None`` or in :data:`VALID_SEVERITIES`."""
    if severity is not None and severity not in _VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"severity must be one of {_VALID_SEVERITIES}",
        )


async def fetch_guard_violations_page(
    conn: asyncpg.Connection,
    *,
    agent_id: str | None,
    severity: str | None,
    unresolved_only: bool,
    limit: int,
    cursor: int | None,
) -> tuple[list[GuardViolationEntry], int | None]:
    """Run the paginated guard-violations query and return ``(entries, next_cursor)``.

    Shared by the JSON ``GET /admin/guard/violations`` route and the HTML
    view-router so both surfaces emit the same shape and cursor semantics.
    """
    validate_severity(severity)
    rows = await conn.fetch(
        """
        SELECT id, ts, run_id, agent_id, violation_type, severity, detail,
               resolution, resolved, resolved_by, resolved_at, resolution_note
          FROM theeyebeta.guard_violations
         WHERE ($1::text IS NULL OR agent_id = $1)
           AND ($2::text IS NULL OR severity = $2)
           AND ($3::boolean IS FALSE OR resolved = false)
           AND ($4::bigint IS NULL OR id < $4)
         ORDER BY id DESC
         LIMIT $5
        """,
        agent_id,
        severity,
        unresolved_only,
        cursor,
        limit + 1,
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    entries = [_row_to_entry(row) for row in page_rows]
    next_cursor = int(page_rows[-1]["id"]) if has_more and page_rows else None
    return entries, next_cursor


async def fetch_guard_violation(
    conn: asyncpg.Connection,
    violation_id: int,
) -> GuardViolationEntry | None:
    """Return the single :class:`GuardViolationEntry` for ``violation_id`` or ``None``."""
    row = await conn.fetchrow(
        """
        SELECT id, ts, run_id, agent_id, violation_type, severity, detail,
               resolution, resolved, resolved_by, resolved_at, resolution_note
          FROM theeyebeta.guard_violations
         WHERE id = $1
        """,
        violation_id,
    )
    return _row_to_entry(row) if row is not None else None


async def resolve_guard_violation_impl(
    conn: asyncpg.Connection,
    *,
    violation_id: int,
    actor: str,
    note: str | None,
) -> ResolveGuardViolationResponse:
    """Mark a guard violation resolved + audit log it. Raise on 404/409.

    Wrapped in a transaction so the row update and the audit-log insert
    succeed or fail together.
    """
    async with conn.transaction():
        existing = await conn.fetchrow(
            """
            SELECT id, resolved
              FROM theeyebeta.guard_violations
             WHERE id = $1
            """,
            violation_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Guard violation not found",
            )
        if existing["resolved"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Guard violation already resolved",
            )

        row = await conn.fetchrow(
            """
            UPDATE theeyebeta.guard_violations
               SET resolved = true,
                   resolved_by = $1,
                   resolved_at = now(),
                   resolution_note = $2
             WHERE id = $3
               AND resolved = false
            RETURNING id, resolved, resolved_by, resolved_at, resolution_note
            """,
            actor,
            note,
            violation_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Guard violation could not be resolved",
            )

        await write_audit_log(
            conn,
            actor=actor,
            action="resolve.guard_violation",
            entity_type="guard_violation",
            entity_id=str(violation_id),
            payload={"note": note},
        )
    return ResolveGuardViolationResponse(
        id=int(row["id"]),
        resolved=bool(row["resolved"]),
        resolved_by=row["resolved_by"],
        resolved_at=row["resolved_at"],
        resolution_note=row["resolution_note"],
    )


def register_guard_routes(limiter: Limiter) -> APIRouter:
    """Attach guard handlers (POST resolve is rate-limited)."""

    @router.get("/violations", response_model=GuardViolationsResponse)
    async def list_violations(
        user: CurrentUser,
        conn: DbConn,
        agent_id: str | None = Query(default=None),
        severity: str | None = Query(default=None),
        unresolved_only: bool = Query(default=False),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
        cursor: int | None = Query(
            default=None,
            description="Return rows with id less than this value (older page).",
        ),
    ) -> GuardViolationsResponse:
        """Paginated guard-violations listing (newest first, cursor by ``id``)."""
        entries, next_cursor = await fetch_guard_violations_page(
            conn,
            agent_id=agent_id,
            severity=severity,
            unresolved_only=unresolved_only,
            limit=limit,
            cursor=cursor,
        )
        log.info(
            "admin_guard_violations_listed",
            count=len(entries),
            agent_id=agent_id,
            severity=severity,
            unresolved_only=unresolved_only,
            sub=user["sub"],
        )
        return GuardViolationsResponse(
            violations=entries,
            limit=limit,
            next_cursor=next_cursor,
        )

    @router.post(
        "/violations/{violation_id}/resolve",
        response_model=ResolveGuardViolationResponse,
    )
    @limiter.limit("20/minute")
    async def resolve_violation(
        request: Request,  # noqa: ARG001 — required by slowapi
        violation_id: int,
        body: ResolveGuardViolationRequest,
        user: dict[str, str] = require_role(Role.OPERATOR),
        conn: DbConn,
    ) -> ResolveGuardViolationResponse:
        """Mark a guard violation as resolved by the current operator."""
        result = await resolve_guard_violation_impl(
            conn,
            violation_id=violation_id,
            actor=_actor(user),
            note=body.note,
        )
        log.info(
            "admin_guard_violation_resolved",
            violation_id=violation_id,
            sub=user["sub"],
        )
        return result

    return router
