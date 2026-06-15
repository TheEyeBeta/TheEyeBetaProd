#!/usr/bin/env python3
"""Dump OpenAPI JSON for a named service to stdout.

Services covered:
  admin  – services/admin_service (port 7200, admin dashboard)
  oms    – services/oms (port 8009, order-management REST API)

Usage (from repo root):
  uv run python scripts/dump_openapi.py admin > docs/api/admin.openapi.json
  uv run python scripts/dump_openapi.py oms   > docs/api/oms.openapi.json

Note: The main external-facing API (services/main_api, port 7000) lives in the
sibling TheEyeBetaDataAPI repository and is not yet migrated here.
See docs/api-gateway.md for the migration plan.
"""

from __future__ import annotations

import json
import sys
import types
from enum import IntEnum
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]


# ── zinc_native.oms stub ─────────────────────────────────────────────────────
# The OMS package imports zinc_native.oms (a C++ nanobind extension).
# Installing a pure-Python stub before importing oms.app lets us call
# app.openapi() without building the C++ layer — mirrors the same technique
# used in tests/conftest.py.


def _install_zinc_native_oms_stub() -> None:
    if "zinc_native.oms" in sys.modules:
        return

    class OrderStatus(IntEnum):
        PendingApproval = 0
        Approved = 1
        Submitted = 2
        Accepted = 3
        PartiallyFilled = 4
        Filled = 5
        Cancelled = 6
        Rejected = 7
        Expired = 8

    class Event(IntEnum):
        Approve = 0
        Reject = 1
        Submit = 2
        Accept = 3
        PartialFill = 4
        Fill = 5
        Cancel = 6
        Expire = 7

    class TransitionErrorCode(IntEnum):
        IllegalTransition = 0
        TerminalState = 1
        InvalidFillQuantity = 2

    class TransitionError:
        def __init__(self, code: Any, from_status: Any, event: Any) -> None:
            self.code = code
            self.from_status = from_status
            self.event = event

    class Order:
        def __init__(self, order_id: str = "", quantity: int = 0) -> None:
            self.order_id = order_id
            self.quantity = quantity
            self.status = OrderStatus.PendingApproval
            self.filled_quantity = 0

    _legal: dict[tuple[Any, Any], Any] = {
        (OrderStatus.PendingApproval, Event.Approve): OrderStatus.Approved,
        (OrderStatus.Approved, Event.Submit): OrderStatus.Submitted,
        (OrderStatus.Submitted, Event.Accept): OrderStatus.Accepted,
        (OrderStatus.Accepted, Event.PartialFill): OrderStatus.PartiallyFilled,
        (OrderStatus.PartiallyFilled, Event.PartialFill): OrderStatus.PartiallyFilled,
        (OrderStatus.Accepted, Event.Fill): OrderStatus.Filled,
        (OrderStatus.PartiallyFilled, Event.Fill): OrderStatus.Filled,
    }
    _terminal = {
        OrderStatus.Filled,
        OrderStatus.Cancelled,
        OrderStatus.Rejected,
        OrderStatus.Expired,
    }

    class TransitionResult:
        def __init__(self, *, ok: bool, order: Any, error: Any = None) -> None:
            self.ok = ok
            self.order = order
            self.error = error

    class StateMachine:
        @staticmethod
        def transition(order: Any, event: Any, fill_quantity: int = 0) -> Any:
            if not order.order_id or order.quantity <= 0:
                return TransitionResult(
                    ok=False,
                    order=order,
                    error=TransitionError(
                        TransitionErrorCode.IllegalTransition, order.status, event
                    ),
                )
            if order.status in _terminal:
                return TransitionResult(
                    ok=False,
                    order=order,
                    error=TransitionError(TransitionErrorCode.TerminalState, order.status, event),
                )
            target = _legal.get((order.status, event))
            if target is None:
                return TransitionResult(
                    ok=False,
                    order=order,
                    error=TransitionError(
                        TransitionErrorCode.IllegalTransition, order.status, event
                    ),
                )
            if event in {Event.PartialFill, Event.Fill}:
                if fill_quantity <= 0:
                    return TransitionResult(
                        ok=False,
                        order=order,
                        error=TransitionError(
                            TransitionErrorCode.InvalidFillQuantity, order.status, event
                        ),
                    )
                order.filled_quantity += fill_quantity
                order.status = (
                    OrderStatus.Filled
                    if order.filled_quantity >= order.quantity
                    else OrderStatus.PartiallyFilled
                )
            else:
                order.status = target
            return TransitionResult(ok=True, order=order)

    class PositionTracker:
        def __init__(self, initial: int = 0) -> None:
            self._legs: dict[str, int] = {}
            self._net = initial

        def apply_fill(self, leg_id: str, delta: int) -> bool:
            if not leg_id:
                return False
            self._legs[leg_id] = self._legs.get(leg_id, 0) + delta
            self._net += delta
            return True

        def leg_position(self, leg_id: str) -> int:
            return self._legs.get(leg_id, 0)

        def net_position(self) -> int:
            return self._net

    stub = types.ModuleType("zinc_native.oms")
    stub.OrderStatus = OrderStatus  # type: ignore[attr-defined]
    stub.Event = Event  # type: ignore[attr-defined]
    stub.TransitionErrorCode = TransitionErrorCode  # type: ignore[attr-defined]
    stub.TransitionError = TransitionError  # type: ignore[attr-defined]
    stub.Order = Order  # type: ignore[attr-defined]
    stub.TransitionResult = TransitionResult  # type: ignore[attr-defined]
    stub.StateMachine = StateMachine  # type: ignore[attr-defined]
    stub.PositionTracker = PositionTracker  # type: ignore[attr-defined]
    stub.is_terminal = lambda status: status in _terminal  # type: ignore[attr-defined]
    sys.modules["zinc_native._zinc_oms"] = stub
    sys.modules["zinc_native.oms"] = stub


# ── service dumpers ──────────────────────────────────────────────────────────


def _dump_admin() -> None:
    """Import admin-service and print its OpenAPI schema."""
    sys.path.insert(0, str(_REPO / "services" / "admin_service"))
    from main import app  # noqa: PLC0415

    print(json.dumps(app.openapi(), indent=2))


def _dump_oms() -> None:
    """Import oms and print its OpenAPI schema."""
    import os  # noqa: PLC0415

    _install_zinc_native_oms_stub()
    # pg_dsn() raises on empty DATABASE_URL; set a syntactically-valid dummy so
    # create_app() can build the route graph without connecting to any DB.
    os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost/dummy")
    sys.path.insert(0, str(_REPO / "services" / "oms" / "src"))
    from oms.app import create_app  # noqa: PLC0415

    print(json.dumps(create_app().openapi(), indent=2))


_SERVICES: dict[str, Any] = {
    "admin": _dump_admin,
    "oms": _dump_oms,
}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in _SERVICES:
        print(f"Usage: {sys.argv[0]} [{' | '.join(_SERVICES)}]", file=sys.stderr)
        sys.exit(1)
    _SERVICES[sys.argv[1]]()
