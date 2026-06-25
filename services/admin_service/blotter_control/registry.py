"""Blotter control gaps and live-order constants."""

from __future__ import annotations

from dataclasses import dataclass

LIVE_STATUSES = frozenset(
    {"approved", "submitted", "accepted", "partially_filled"},
)
CANCELLABLE_STATUSES = frozenset(
    {"approved", "submitted", "accepted", "partially_filled"},
)
REPLACEABLE_STATUSES = frozenset(
    {"submitted", "accepted", "partially_filled"},
)
STALE_POSITIONS_HOURS = 24


@dataclass(frozen=True, slots=True)
class BlotterControlGap:
    action: str
    reason: str


CANCEL_BROKER_GAP = BlotterControlGap(
    action="cancel_live_order",
    reason=(
        "Cancel updates local order status only; "
        "broker adapter cancel endpoint not wired from admin."
    ),
)

REPLACE_BROKER_GAP = BlotterControlGap(
    action="replace_live_order",
    reason=(
        "Replace persists amended qty/price in orders.metadata; "
        "broker replace not wired from admin."
    ),
)

RECONCILIATION_PERSIST_GAP = BlotterControlGap(
    action="reconciliation_drift_history",
    reason=(
        "Drift is computed on demand from broker vs Postgres; "
        "OMS loop does not persist snapshots for admin history."
    ),
)

BROKER_TEST_GAP = BlotterControlGap(
    action="broker_test_connection",
    reason="Health probe only; does not validate Alpaca order submission path.",
)
