"""Shared pytest fixtures for workspace-level tests."""

from __future__ import annotations

import sys
import types
from enum import IntEnum
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_OMS_SRC = _ROOT / "services" / "oms" / "src"
_BROKER_SRC = _ROOT / "services" / "broker_adapter_alpaca" / "src"

for _path in (_OMS_SRC, _BROKER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def _install_oms_stub() -> None:
    """Minimal OMS stub when the C++ extension is not built."""
    if "zinc_native._zinc_oms" in sys.modules:
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
        def __init__(
            self,
            code: TransitionErrorCode,
            from_status: OrderStatus,
            event: Event,
        ) -> None:
            self.code = code
            self.from_status = from_status
            self.event = event

    class Order:
        def __init__(self, order_id: str = "", quantity: int = 0) -> None:
            self.order_id = order_id
            self.quantity = quantity
            self.status = OrderStatus.PendingApproval
            self.filled_quantity = 0

    legal: dict[tuple[OrderStatus, Event], OrderStatus] = {
        (OrderStatus.PendingApproval, Event.Approve): OrderStatus.Approved,
        (OrderStatus.Approved, Event.Submit): OrderStatus.Submitted,
        (OrderStatus.Submitted, Event.Accept): OrderStatus.Accepted,
        (OrderStatus.Accepted, Event.PartialFill): OrderStatus.PartiallyFilled,
        (OrderStatus.PartiallyFilled, Event.PartialFill): OrderStatus.PartiallyFilled,
        (OrderStatus.Accepted, Event.Fill): OrderStatus.Filled,
        (OrderStatus.PartiallyFilled, Event.Fill): OrderStatus.Filled,
    }
    terminal = {
        OrderStatus.Filled,
        OrderStatus.Cancelled,
        OrderStatus.Rejected,
        OrderStatus.Expired,
    }

    class TransitionResult:
        def __init__(
            self,
            *,
            ok: bool,
            order: Order,
            error: TransitionError | None = None,
        ) -> None:
            self.ok = ok
            self.order = order
            self.error = error

    class StateMachine:
        @staticmethod
        def transition(order: Order, event: Event, fill_quantity: int = 0) -> TransitionResult:
            if not order.order_id or order.quantity <= 0:
                err = TransitionError(
                    TransitionErrorCode.IllegalTransition,
                    order.status,
                    event,
                )
                return TransitionResult(ok=False, order=order, error=err)
            if order.status in terminal:
                err = TransitionError(TransitionErrorCode.TerminalState, order.status, event)
                return TransitionResult(ok=False, order=order, error=err)
            target = legal.get((order.status, event))
            if target is None:
                err = TransitionError(
                    TransitionErrorCode.IllegalTransition,
                    order.status,
                    event,
                )
                return TransitionResult(ok=False, order=order, error=err)
            if event in {Event.PartialFill, Event.Fill}:
                if fill_quantity <= 0:
                    err = TransitionError(
                        TransitionErrorCode.InvalidFillQuantity,
                        order.status,
                        event,
                    )
                    return TransitionResult(ok=False, order=order, error=err)
                order.filled_quantity += fill_quantity
                if order.filled_quantity >= order.quantity:
                    order.status = OrderStatus.Filled
                else:
                    order.status = OrderStatus.PartiallyFilled
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
    stub.OrderStatus = OrderStatus
    stub.Event = Event
    stub.TransitionErrorCode = TransitionErrorCode
    stub.TransitionError = TransitionError
    stub.Order = Order
    stub.TransitionResult = TransitionResult
    stub.StateMachine = StateMachine
    stub.PositionTracker = PositionTracker
    stub.is_terminal = lambda status: status in terminal
    sys.modules["zinc_native._zinc_oms"] = stub
    sys.modules["zinc_native.oms"] = stub


_install_oms_stub()


class _RecordingNats:
    """In-memory NATS stub that records published messages.

    Defined here (root conftest) so test_frontend.py can import it as
    ``tests.conftest._RecordingNats`` without hitting the service-local
    admin conftest (which pytest caches under a different sys.modules key).
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))

    async def drain(self) -> None:
        return None

    async def close(self) -> None:
        return None
