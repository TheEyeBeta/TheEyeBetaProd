"""OMS status string ↔ zinc_native.oms.OrderStatus mapping."""

from __future__ import annotations

from zinc_native import oms

DB_TO_OMS: dict[str, oms.OrderStatus] = {
    "pending_approval": oms.OrderStatus.PendingApproval,
    "approved": oms.OrderStatus.Approved,
    "submitted": oms.OrderStatus.Submitted,
    "accepted": oms.OrderStatus.Accepted,
    "partially_filled": oms.OrderStatus.PartiallyFilled,
    "filled": oms.OrderStatus.Filled,
    "cancelled": oms.OrderStatus.Cancelled,
    "rejected": oms.OrderStatus.Rejected,
    "expired": oms.OrderStatus.Expired,
}

OMS_TO_DB: dict[oms.OrderStatus, str] = {value: key for key, value in DB_TO_OMS.items()}


def leg_id(portfolio_id: str, instrument_id: int) -> str:
    """Build a stable position-tracker leg key."""
    return f"p{portfolio_id}:i{instrument_id}"
