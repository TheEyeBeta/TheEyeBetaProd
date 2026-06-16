"""Admin orders API — pending queue, detail, approve, reject."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import nats
import structlog
from audit_log import write_audit_log
from auth import CurrentUser
from deps import DbConn, NatsClient
from fastapi import APIRouter, HTTPException, Request, status
from rbac import Role, require_role
from slowapi import Limiter

from zinc_schemas.admin_dto import (
    ApproveOrderRequest,
    ApproveOrderResponse,
    InstrumentSummary,
    OrderDetailResponse,
    OrderSummary,
    PendingOrdersResponse,
    RejectOrderRequest,
    RejectOrderResponse,
)

log = structlog.get_logger()

router = APIRouter(prefix="/orders", tags=["orders"])

_SELECT_ORDER = """
SELECT
    o.id,
    o.client_order_id,
    o.portfolio_id,
    o.side,
    o.order_type,
    o.qty,
    o.limit_price,
    o.stop_price,
    o.time_in_force,
    o.status,
    o.filled_qty,
    o.avg_fill_price,
    o.metadata,
    o.approved_by,
    o.approved_at,
    o.created_at,
    o.updated_at,
    i.id AS instrument_id,
    i.symbol AS instrument_symbol,
    e.code AS exchange_code
  FROM theeyebeta.orders o
  JOIN theeyebeta.instruments i ON i.id = o.instrument_id
  LEFT JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
"""


def _row_to_summary(row: asyncpg.Record) -> OrderSummary:
    """Map a joined order row to :class:`OrderSummary`."""
    return OrderSummary(
        id=row["id"],
        client_order_id=row["client_order_id"],
        portfolio_id=row["portfolio_id"],
        instrument=InstrumentSummary(
            id=int(row["instrument_id"]),
            symbol=row["instrument_symbol"],
            exchange_code=row["exchange_code"],
        ),
        side=row["side"],
        order_type=row["order_type"],
        qty=Decimal(str(row["qty"])),
        limit_price=Decimal(str(row["limit_price"])) if row["limit_price"] is not None else None,
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_detail(row: asyncpg.Record) -> OrderDetailResponse:
    """Map a joined order row to :class:`OrderDetailResponse`."""
    summary = _row_to_summary(row)
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        metadata = {}
    return OrderDetailResponse(
        **summary.model_dump(),
        stop_price=Decimal(str(row["stop_price"])) if row["stop_price"] is not None else None,
        time_in_force=row["time_in_force"],
        filled_qty=Decimal(str(row["filled_qty"])),
        avg_fill_price=(
            Decimal(str(row["avg_fill_price"])) if row["avg_fill_price"] is not None else None
        ),
        metadata=metadata,
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        updated_at=row["updated_at"],
    )


async def _fetch_order(conn: asyncpg.Connection, order_id: UUID) -> asyncpg.Record | None:
    """Load one order by id."""
    return await conn.fetchrow(
        f"{_SELECT_ORDER} WHERE o.id = $1",
        order_id,
    )


def _actor(user: dict[str, str]) -> str:
    """Build audit actor string from JWT subject."""
    return f"admin-api:{user['sub']}"


async def approve_pending_order(
    conn: asyncpg.Connection,
    nats_client: nats.NATS,
    *,
    order_id: UUID,
    actor: str,
    note: str | None,
) -> ApproveOrderResponse:
    """Approve one pending order and publish ``orders.approved.{id}``.

    Shared by the JSON ``POST /admin/orders/{id}/approve`` route and the
    HTML view-router fragment that swaps a single table row. Calling this
    helper avoids an HTTP self-loop between the admin views and the JSON API.

    Raises:
        HTTPException: 404 if the order doesn't exist; 409 if it's not
            currently ``pending_approval``.
    """
    async with conn.transaction():
        existing = await _fetch_order(conn, order_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if existing["status"] != "pending_approval":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Order status is {existing['status']}, expected pending_approval",
            )
        row = await conn.fetchrow(
            """
            UPDATE theeyebeta.orders
               SET status = 'approved',
                   approved_by = $1,
                   approved_at = now(),
                   updated_at = now()
             WHERE id = $2
               AND status = 'pending_approval'
             RETURNING id, status, approved_by, approved_at
            """,
            actor,
            order_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order could not be approved",
            )
        await write_audit_log(
            conn,
            actor=actor,
            action="approve.order",
            entity_type="order",
            entity_id=str(order_id),
            payload={"note": note} if note else {},
        )

    nats_payload: dict[str, Any] = {
        "order_id": str(order_id),
        "approved_by": actor,
        "status": "approved",
    }
    if note:
        nats_payload["note"] = note
    subject = f"orders.approved.{order_id}"
    await nats_client.publish(subject, json.dumps(nats_payload, default=str).encode())
    log.info("admin_order_approved", order_id=str(order_id), subject=subject, actor=actor)
    return ApproveOrderResponse(
        id=row["id"],
        status=row["status"],
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
    )


async def reject_pending_order(
    conn: asyncpg.Connection,
    *,
    order_id: UUID,
    actor: str,
    reason: str,
) -> RejectOrderResponse:
    """Reject one pending order and write the reason to ``metadata.rejection_reason``.

    Raises:
        HTTPException: 404 if the order doesn't exist; 409 if it's not
            currently ``pending_approval``.
    """
    async with conn.transaction():
        existing = await _fetch_order(conn, order_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if existing["status"] != "pending_approval":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Order status is {existing['status']}, expected pending_approval",
            )
        row = await conn.fetchrow(
            """
            UPDATE theeyebeta.orders
               SET status = 'rejected',
                   metadata = COALESCE(metadata, '{}'::jsonb)
                       || jsonb_build_object('rejection_reason', $1::text),
                   updated_at = now()
             WHERE id = $2
               AND status = 'pending_approval'
             RETURNING id, status, metadata
            """,
            reason,
            order_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order could not be rejected",
            )
        await write_audit_log(
            conn,
            actor=actor,
            action="reject.order",
            entity_type="order",
            entity_id=str(order_id),
            payload={"rejection_reason": reason},
        )

    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        metadata = {}
    log.info("admin_order_rejected", order_id=str(order_id), actor=actor)
    return RejectOrderResponse(id=row["id"], status=row["status"], metadata=metadata)


def register_orders_routes(limiter: Limiter) -> APIRouter:
    """Attach rate-limited order handlers to the shared router."""

    @router.get("/pending", response_model=PendingOrdersResponse)
    async def list_pending_orders(
        user: CurrentUser,
        conn: DbConn,
    ) -> PendingOrdersResponse:
        """List orders awaiting operator approval."""
        rows = await conn.fetch(
            f"""
            {_SELECT_ORDER}
             WHERE o.status = 'pending_approval'
             ORDER BY o.created_at DESC
            """,
        )
        orders = [_row_to_summary(row) for row in rows]
        log.info("admin_orders_pending_listed", count=len(orders), sub=user["sub"])
        return PendingOrdersResponse(orders=orders, total=len(orders))

    @router.get("/{order_id}", response_model=OrderDetailResponse)
    async def get_order(
        order_id: UUID,
        user: CurrentUser,
        conn: DbConn,
    ) -> OrderDetailResponse:
        """Return one order with instrument join."""
        row = await _fetch_order(conn, order_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        log.info("admin_order_fetched", order_id=str(order_id), sub=user["sub"])
        return _row_to_detail(row)

    @router.post("/{order_id}/approve", response_model=ApproveOrderResponse)
    @limiter.limit("20/minute")
    async def approve_order(
        request: Request,  # noqa: ARG001 — required by slowapi
        order_id: UUID,
        body: ApproveOrderRequest,
        user: dict[str, str] = require_role(Role.OPERATOR),
        conn: DbConn,
        nats: NatsClient,
    ) -> ApproveOrderResponse:
        """Transition ``pending_approval`` → ``approved`` and publish NATS event."""
        return await approve_pending_order(
            conn,
            nats,
            order_id=order_id,
            actor=_actor(user),
            note=body.note,
        )

    @router.post("/{order_id}/reject", response_model=RejectOrderResponse)
    @limiter.limit("20/minute")
    async def reject_order(
        request: Request,  # noqa: ARG001 — required by slowapi
        order_id: UUID,
        body: RejectOrderRequest,
        user: dict[str, str] = require_role(Role.OPERATOR),
        conn: DbConn,
    ) -> RejectOrderResponse:
        """Transition ``pending_approval`` → ``rejected`` with reason in metadata."""
        return await reject_pending_order(
            conn,
            order_id=order_id,
            actor=_actor(user),
            reason=body.rejection_reason,
        )

    return router
