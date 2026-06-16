"""Admin audit API — log viewer, chain verify proxy, checkpoints."""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import structlog
from auth import CurrentUser
from deps import DbConn, SettingsDep
from fastapi import APIRouter, HTTPException, Query, status
from rbac import Role, require_role
from settings import Settings

from zinc_schemas.admin_dto import (
    AuditCheckpointsResponse,
    AuditCheckpointSummary,
    AuditLogEntry,
    AuditLogPageResponse,
    AuditVerifyResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/audit", tags=["audit"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _parse_payload(raw: object) -> dict[str, Any]:
    """Normalize ``audit_log.payload`` from asyncpg."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _row_to_entry(row: asyncpg.Record) -> AuditLogEntry:
    """Map a DB row to :class:`AuditLogEntry`."""
    return AuditLogEntry(
        id=int(row["id"]),
        ts=row["ts"],
        actor=row["actor"],
        action=row["action"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        payload=_parse_payload(row["payload"]),
    )


async def fetch_audit_log_page(
    conn: asyncpg.Connection,
    *,
    entity_id: str | None,
    actor: str | None,
    since: datetime | None,
    limit: int,
    cursor: int | None,
) -> tuple[list[AuditLogEntry], int | None]:
    """Run the paginated audit-log query and return ``(entries, next_cursor)``.

    Shared by the JSON ``GET /admin/audit/log`` route and the HTML view-router
    fragment so both surface the same data and cursor semantics. The cursor
    is the smallest ``id`` returned so far — pass it back to walk the chain
    backwards in time.
    """
    rows = await conn.fetch(
        """
        SELECT id, ts, actor, action, entity_type, entity_id, payload
          FROM theeyebeta.audit_log
         WHERE ($1::text IS NULL OR entity_id = $1)
           AND ($2::text IS NULL OR actor = $2)
           AND ($3::timestamptz IS NULL OR ts >= $3)
           AND ($4::bigint IS NULL OR id < $4)
         ORDER BY id DESC
         LIMIT $5
        """,
        entity_id,
        actor,
        since,
        cursor,
        limit + 1,
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    entries = [_row_to_entry(row) for row in page_rows]
    next_cursor = int(page_rows[-1]["id"]) if has_more and page_rows else None
    return entries, next_cursor


async def call_audit_service_verify(
    settings: Settings,
    *,
    from_ts: datetime,
    to_ts: datetime,
) -> AuditVerifyResponse:
    """Proxy hash-chain verification to audit-service ``GET /audit/verify``.

    Note: audit-service exposes GET (not POST) with ``from`` / ``to`` query parameters.
    """
    if to_ts < from_ts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'to' must be >= 'from'",
        )
    base = settings.audit_service_url.rstrip("/")
    url = f"{base}/audit/verify"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                url,
                params={"from": from_ts.isoformat(), "to": to_ts.isoformat()},
            )
    except httpx.HTTPError as exc:
        log.error("audit_service_verify_unreachable", url=url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit-service is unreachable",
        ) from exc

    if response.status_code == status.HTTP_400_BAD_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.text,
        )
    if response.status_code >= 500:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit-service verify failed",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )

    data = response.json()
    chain_status = str(data.get("status", ""))
    return AuditVerifyResponse(
        ok=chain_status == "OK",
        mismatch_at_id=data.get("first_bad_row_id"),
        rows_checked=int(data.get("rows_checked", 0)),
        detail=data.get("detail"),
    )


def register_audit_routes() -> APIRouter:
    """Attach audit read handlers (GET only — default rate limits apply)."""

    @router.get("/log", response_model=AuditLogPageResponse)
    async def list_audit_log(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
        entity_id: str | None = Query(default=None),
        actor: str | None = Query(default=None),
        since: datetime | None = Query(default=None),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
        cursor: int | None = Query(
            default=None,
            description="Return rows with id less than this value (older page).",
        ),
    ) -> AuditLogPageResponse:
        """Paginated ``audit_log`` listing (newest first, cursor by ``id``)."""
        entries, next_cursor = await fetch_audit_log_page(
            conn,
            entity_id=entity_id,
            actor=actor,
            since=since,
            limit=limit,
            cursor=cursor,
        )
        log.info(
            "admin_audit_log_listed",
            count=len(entries),
            sub=user["sub"],
            has_more=next_cursor is not None,
        )
        return AuditLogPageResponse(entries=entries, limit=limit, next_cursor=next_cursor)

    @router.get("/chain/verify", response_model=AuditVerifyResponse)
    async def verify_audit_chain(
        settings: SettingsDep,
        conn: DbConn,
        user: dict[str, str] = require_role(Role.COMPLIANCE),
    ) -> AuditVerifyResponse:
        """Verify hash-chain for configured lookback window via audit-service."""
        from datetime import UTC, datetime, timedelta

        to_ts = datetime.now(tz=UTC)
        from_ts = to_ts - timedelta(hours=settings.audit_verify_hours)
        result = await call_audit_service_verify(settings, from_ts=from_ts, to_ts=to_ts)
        with suppress(asyncpg.UndefinedTableError):
            await conn.execute(
                """
                INSERT INTO theeyebeta.audit_chain_status
                    (verified_at, valid, entries_checked, first_invalid_seq, error_message)
                VALUES (now(), $1, $2, $3, $4)
                """,
                result.ok,
                result.rows_checked,
                result.mismatch_at_id,
                None if result.ok else result.detail,
            )
        log.info("admin_audit_chain_verify", ok=result.ok, sub=user["sub"])
        return result

    @router.get("/verify", response_model=AuditVerifyResponse)
    async def verify_audit_log(
        settings: SettingsDep,
        from_ts: datetime = Query(..., alias="from"),
        to_ts: datetime = Query(..., alias="to"),
        user: dict[str, str] = require_role(Role.COMPLIANCE),
    ) -> AuditVerifyResponse:
        """Verify hash-chain integrity for a timestamp range via audit-service."""
        result = await call_audit_service_verify(settings, from_ts=from_ts, to_ts=to_ts)
        log.info(
            "admin_audit_verify",
            ok=result.ok,
            mismatch_at_id=result.mismatch_at_id,
            sub=user["sub"],
        )
        return result

    @router.get("/checkpoints", response_model=AuditCheckpointsResponse)
    async def list_checkpoints(
        conn: DbConn,
        user: dict[str, str] = require_role(Role.READ_ONLY),
    ) -> AuditCheckpointsResponse:
        """List WORM checkpoint metadata rows."""
        rows = await conn.fetch(
            """
            SELECT id, checkpoint_id, last_row_id, signing_ts, row_count, s3_uri, created_at
              FROM theeyebeta.audit_checkpoints
             ORDER BY signing_ts DESC
            """,
        )
        checkpoints = [
            AuditCheckpointSummary(
                id=row["id"],
                checkpoint_id=row["checkpoint_id"],
                last_row_id=int(row["last_row_id"]),
                signing_ts=row["signing_ts"],
                row_count=int(row["row_count"]),
                s3_uri=row["s3_uri"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        log.info("admin_audit_checkpoints_listed", count=len(checkpoints), sub=user["sub"])
        return AuditCheckpointsResponse(checkpoints=checkpoints)

    return router
