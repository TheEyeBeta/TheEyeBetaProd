"""Admin proposals API — list, detail, approve (with validation backtest), reject."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import nats as nats_module
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, NatsClient
from fastapi import APIRouter, HTTPException, Query, Request, status
from rbac import Role, require_role
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    ApproveProposalRequest,
    ApproveProposalResponse,
    ProposalDetail,
    ProposalsListResponse,
    ProposalSummary,
    RejectProposalRequest,
    RejectProposalResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/proposals", tags=["proposals"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_VALID_STATUSES = ("pending", "approved", "rejected", "superseded", "applied")
_VALID_CATEGORIES = (
    "strategy_param",
    "agent_constitution",
    "risk_rule",
    "compliance_rule_nonregulatory",
    "new_strategy",
    "architecture",
)

# Public re-exports for the HTML view layer.
VALID_PROPOSAL_STATUSES: tuple[str, ...] = _VALID_STATUSES
VALID_PROPOSAL_CATEGORIES: tuple[str, ...] = _VALID_CATEGORIES
PROPOSALS_DEFAULT_LIMIT = _DEFAULT_LIMIT
PROPOSALS_MAX_LIMIT = _MAX_LIMIT


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


def _parse_jsonb(raw: object) -> dict[str, Any]:
    """Coerce asyncpg JSONB output into a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _row_to_summary(row: asyncpg.Record) -> ProposalSummary:
    """Map a DB row to :class:`ProposalSummary`."""
    return ProposalSummary(
        id=row["id"],
        proposed_by=row["proposed_by"],
        run_id=row["run_id"],
        category=row["category"],
        target=row["target"],
        rationale=row["rationale"],
        status=row["status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_notes=row["review_notes"],
        validation_backtest_id=row["validation_backtest_id"],
        created_at=row["created_at"],
    )


def _row_to_detail(row: asyncpg.Record) -> ProposalDetail:
    """Map a DB row to :class:`ProposalDetail` (full row)."""
    return ProposalDetail(
        id=row["id"],
        proposed_by=row["proposed_by"],
        run_id=row["run_id"],
        category=row["category"],
        target=row["target"],
        rationale=row["rationale"],
        status=row["status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_notes=row["review_notes"],
        validation_backtest_id=row["validation_backtest_id"],
        created_at=row["created_at"],
        current_value=_parse_jsonb(row["current_value"]),
        proposed_value=_parse_jsonb(row["proposed_value"]),
        evidence=_parse_jsonb(row["evidence"]),
        estimated_impact=(
            _parse_jsonb(row["estimated_impact"]) if row["estimated_impact"] is not None else None
        ),
        applied_at=row["applied_at"],
        applied_commit_sha=row["applied_commit_sha"],
    )


async def fetch_proposals_page(
    conn: asyncpg.Connection,
    *,
    proposal_status: str | None = None,
    category: str | None = None,
    proposed_by: str | None = None,
    target: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    cursor: datetime | None = None,
) -> ProposalsListResponse:
    """Paginated proposals listing (newest first) for one filter combo.

    Validates ``proposal_status``/``category`` against the allow-lists and
    raises 422 on mismatches — same contract as the JSON router so the HTML
    view can reuse the body without re-validating.
    """
    if limit < 1 or limit > _MAX_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"limit must be between 1 and {_MAX_LIMIT}",
        )
    if proposal_status is not None and proposal_status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of {_VALID_STATUSES}",
        )
    if category is not None and category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"category must be one of {_VALID_CATEGORIES}",
        )

    rows = await conn.fetch(
        """
        SELECT id, proposed_by, run_id, category, target, rationale, status,
               reviewed_by, reviewed_at, review_notes,
               validation_backtest_id, created_at
          FROM theeyebeta.proposals
         WHERE ($1::text IS NULL OR status = $1)
           AND ($2::text IS NULL OR category = $2)
           AND ($3::text IS NULL OR proposed_by = $3)
           AND ($4::text IS NULL OR target = $4)
           AND ($5::timestamptz IS NULL OR created_at < $5)
         ORDER BY created_at DESC, id DESC
         LIMIT $6
        """,
        proposal_status,
        category,
        proposed_by,
        target,
        cursor,
        limit + 1,
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    proposals = [_row_to_summary(row) for row in page_rows]
    next_cursor = page_rows[-1]["created_at"] if has_more and page_rows else None
    return ProposalsListResponse(
        proposals=proposals,
        limit=limit,
        next_cursor=next_cursor,
    )


async def fetch_proposal_detail(
    conn: asyncpg.Connection,
    proposal_id: UUID,
) -> ProposalDetail | None:
    """Return one full proposal row or ``None`` when the id is unknown."""
    row = await conn.fetchrow(
        """
        SELECT id, proposed_by, run_id, category, target, rationale, status,
               reviewed_by, reviewed_at, review_notes,
               validation_backtest_id, created_at,
               current_value, proposed_value, evidence, estimated_impact,
               applied_at, applied_commit_sha
          FROM theeyebeta.proposals
         WHERE id = $1
        """,
        proposal_id,
    )
    if row is None:
        return None
    return _row_to_detail(row)


async def _create_validation_backtest(
    conn: asyncpg.Connection,
    *,
    proposal_id: UUID,
    body: ApproveProposalRequest,
) -> UUID:
    """Insert a ``backtest_runs`` row keyed to the proposal.

    Args:
        conn: Active asyncpg connection (caller controls the transaction).
        proposal_id: ID of the proposal being approved.
        body: Approval request — ``strategy_id``, ``start_date``, ``end_date``
            and ``universe`` must be present when this helper is called.

    Returns:
        The new ``backtest_runs.id``.

    Raises:
        HTTPException: 422 when required fields are missing or the strategy
            does not exist.
    """
    if (
        body.strategy_id is None
        or body.start_date is None
        or body.end_date is None
        or body.universe is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "strategy_id, start_date, end_date, universe are required when "
                "skip_backtest is false"
            ),
        )
    if body.start_date > body.end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be <= end_date",
        )

    strategy_exists = await conn.fetchval(
        "SELECT 1 FROM theeyebeta.strategies WHERE id = $1",
        body.strategy_id,
    )
    if not strategy_exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown strategy_id '{body.strategy_id}'",
        )

    backtest_id = uuid4()
    config = {
        "triggered_by_proposal": str(proposal_id),
        "kind": "validation",
    }
    git_sha = body.git_sha or "pending"
    await conn.execute(
        """
        INSERT INTO theeyebeta.backtest_runs (
            id, strategy_id, start_date, end_date, universe,
            config, git_sha, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'running')
        """,
        backtest_id,
        body.strategy_id,
        body.start_date,
        body.end_date,
        body.universe,
        json.dumps(config),
        git_sha,
    )
    return backtest_id


async def approve_proposal_impl(
    conn: asyncpg.Connection,
    nats: nats_module.NATS,
    *,
    proposal_id: UUID,
    body: ApproveProposalRequest,
    actor: str,
) -> ApproveProposalResponse:
    """Approve a pending proposal, optionally enqueueing a validation backtest.

    Behaviour mirrors ``POST /admin/proposals/{id}/approve`` exactly — same
    404 / 409 / 422 raises, same audit log row, same NATS publish.
    """
    audit_payload = body.model_dump(mode="json")

    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id, status FROM theeyebeta.proposals WHERE id = $1",
            proposal_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found",
            )
        if existing["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Proposal status is {existing['status']}, expected pending"),
            )

        backtest_id: UUID | None = None
        if not body.skip_backtest:
            backtest_id = await _create_validation_backtest(
                conn,
                proposal_id=proposal_id,
                body=body,
            )

        row = await conn.fetchrow(
            """
            UPDATE theeyebeta.proposals
               SET status = 'approved',
                   reviewed_by = $1,
                   reviewed_at = now(),
                   review_notes = $2,
                   validation_backtest_id = COALESCE($3, validation_backtest_id)
             WHERE id = $4
               AND status = 'pending'
             RETURNING id, status, reviewed_by, reviewed_at,
                       review_notes, validation_backtest_id
            """,
            actor,
            body.review_notes,
            backtest_id,
            proposal_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Proposal could not be approved",
            )

        await write_audit_log(
            conn,
            actor=actor,
            action="approve.proposal",
            entity_type="proposal",
            entity_id=str(proposal_id),
            payload={
                **audit_payload,
                "validation_backtest_id": str(backtest_id) if backtest_id else None,
            },
        )

    if backtest_id is not None:
        event = {
            "proposal_id": str(proposal_id),
            "backtest_run_id": str(backtest_id),
            "strategy_id": body.strategy_id,
            "start_date": body.start_date.isoformat() if body.start_date else None,
            "end_date": body.end_date.isoformat() if body.end_date else None,
            "universe": body.universe,
            "requested_by": actor,
        }
        try:
            await nats.publish(
                "backtests.requested",
                json.dumps(event).encode("utf-8"),
            )
        except (nats_module.errors.Error, OSError) as exc:
            log.warning(
                "admin_backtest_request_publish_failed",
                proposal_id=str(proposal_id),
                backtest_run_id=str(backtest_id),
                error=str(exc),
            )

    return ApproveProposalResponse(
        id=row["id"],
        status=row["status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        validation_backtest_id=row["validation_backtest_id"],
        review_notes=row["review_notes"],
    )


async def reject_proposal_impl(
    conn: asyncpg.Connection,
    *,
    proposal_id: UUID,
    body: RejectProposalRequest,
    actor: str,
) -> RejectProposalResponse:
    """Reject a pending proposal. Mirrors ``POST /admin/proposals/{id}/reject``."""
    audit_payload = body.model_dump(mode="json")

    async with conn.transaction():
        existing = await conn.fetchrow(
            "SELECT id, status FROM theeyebeta.proposals WHERE id = $1",
            proposal_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found",
            )
        if existing["status"] != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Proposal status is {existing['status']}, expected pending"),
            )

        row = await conn.fetchrow(
            """
            UPDATE theeyebeta.proposals
               SET status = 'rejected',
                   reviewed_by = $1,
                   reviewed_at = now(),
                   review_notes = $2
             WHERE id = $3
               AND status = 'pending'
             RETURNING id, status, reviewed_by, reviewed_at, review_notes
            """,
            actor,
            body.review_notes,
            proposal_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Proposal could not be rejected",
            )

        await write_audit_log(
            conn,
            actor=actor,
            action="reject.proposal",
            entity_type="proposal",
            entity_id=str(proposal_id),
            payload=audit_payload,
        )

    return RejectProposalResponse(
        id=row["id"],
        status=row["status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_notes=row["review_notes"],
    )


async def fetch_backtest_status(
    conn: asyncpg.Connection,
    backtest_id: UUID,
) -> dict[str, Any] | None:
    """Return the ``status`` / ``started_at`` / ``completed_at`` of a backtest run."""
    row = await conn.fetchrow(
        """
        SELECT id, status, created_at, started_at, completed_at
          FROM theeyebeta.backtest_runs
         WHERE id = $1
        """,
        backtest_id,
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def register_proposals_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited proposal handlers."""

    @router.get("", response_model=ProposalsListResponse)
    async def list_proposals(
        user: CurrentUser,
        conn: DbConn,
        proposal_status: str | None = Query(default=None, alias="status"),
        category: str | None = Query(default=None),
        proposed_by: str | None = Query(default=None),
        target: str | None = Query(default=None),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
        cursor: datetime | None = Query(
            default=None,
            description="Return rows with created_at < this value (older page).",
        ),
    ) -> ProposalsListResponse:
        """Paginated proposals listing (newest first)."""
        response = await fetch_proposals_page(
            conn,
            proposal_status=proposal_status,
            category=category,
            proposed_by=proposed_by,
            target=target,
            limit=limit,
            cursor=cursor,
        )
        log.info(
            "admin_proposals_listed",
            count=len(response.proposals),
            status=proposal_status,
            category=category,
            sub=user["sub"],
        )
        return response

    @router.get("/{proposal_id}", response_model=ProposalDetail)
    async def get_proposal(
        proposal_id: UUID,
        user: CurrentUser,
        conn: DbConn,
    ) -> ProposalDetail:
        """Return one proposal with full payload."""
        detail = await fetch_proposal_detail(conn, proposal_id)
        if detail is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proposal not found",
            )
        log.info("admin_proposal_fetched", proposal_id=str(proposal_id), sub=user["sub"])
        return detail

    @router.post("/{proposal_id}/approve", response_model=ApproveProposalResponse)
    @limiter.limit("20/minute")
    async def approve_proposal(
        request: Request,  # noqa: ARG001 — required by slowapi
        proposal_id: UUID,
        body: ApproveProposalRequest,
        user: dict[str, str] = require_role(Role.OPERATOR),
        conn: DbConn,
        nats: NatsClient,
    ) -> ApproveProposalResponse:
        """Transition a proposal to ``approved`` and request a validation backtest."""
        actor = _actor(user)
        response = await approve_proposal_impl(
            conn,
            nats,
            proposal_id=proposal_id,
            body=body,
            actor=actor,
        )
        log.info(
            "admin_proposal_approved",
            proposal_id=str(proposal_id),
            backtest_run_id=(
                str(response.validation_backtest_id) if response.validation_backtest_id else None
            ),
            sub=user["sub"],
        )
        return response

    @router.post("/{proposal_id}/reject", response_model=RejectProposalResponse)
    @limiter.limit("20/minute")
    async def reject_proposal(
        request: Request,  # noqa: ARG001 — required by slowapi
        proposal_id: UUID,
        body: RejectProposalRequest,
        user: dict[str, str] = require_role(Role.OPERATOR),
        conn: DbConn,
    ) -> RejectProposalResponse:
        """Transition a proposal to ``rejected`` with a required ``review_notes``."""
        actor = _actor(user)
        response = await reject_proposal_impl(
            conn,
            proposal_id=proposal_id,
            body=body,
            actor=actor,
        )
        log.info(
            "admin_proposal_rejected",
            proposal_id=str(proposal_id),
            sub=user["sub"],
        )
        return response

    return router
