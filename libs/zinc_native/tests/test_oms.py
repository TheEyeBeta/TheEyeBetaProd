"""pytest mirrors of cpp/tests/oms_*_test.cpp."""

from __future__ import annotations

import sys as _sys
import threading

import numpy as np
import pytest

_zinc_oms = _sys.modules.get("zinc_native._zinc_oms")
if _zinc_oms is None:
    pytest.importorskip("zinc_native._zinc_oms", reason="C++ kernels not compiled — run make build-cpp")
elif not getattr(_zinc_oms, "__file__", None):
    pytest.skip("C++ kernels not compiled — zinc_native.oms is a Python stub", allow_module_level=True)
from zinc_native import oms

REFERENCE_FILLED_QUANTITY = 42
CONCURRENT_FILL_COUNT = 1000
CONCURRENT_THREADS = 10
REFERENCE_NET_POSITION = 10000


def _make_order(quantity: int = 100) -> oms.Order:
    return oms.Order(order_id="ORD-1", quantity=quantity)


def _expect_success(result: oms.TransitionResult, expected_status: oms.OrderStatus) -> None:
    assert result.ok
    assert result.order.status == expected_status


def _expect_failure(result: oms.TransitionResult, expected_code: oms.TransitionErrorCode) -> None:
    assert not result.ok
    assert result.error.code == expected_code


class TestStateMachine:
    def test_happy_path_hand_computed_partial_fills(self) -> None:
        order = _make_order(100)

        _expect_success(oms.StateMachine.transition(order, oms.Event.Approve), oms.OrderStatus.Approved)
        _expect_success(oms.StateMachine.transition(order, oms.Event.Submit), oms.OrderStatus.Submitted)
        _expect_success(oms.StateMachine.transition(order, oms.Event.Accept), oms.OrderStatus.Accepted)

        result = oms.StateMachine.transition(order, oms.Event.PartialFill, 40)
        _expect_success(result, oms.OrderStatus.PartiallyFilled)
        assert order.filled_quantity == 40

        result = oms.StateMachine.transition(order, oms.Event.PartialFill, 60)
        _expect_success(result, oms.OrderStatus.Filled)
        assert order.filled_quantity == 100

    def test_empty_and_invalid_input_returns_error(self) -> None:
        empty_id = oms.Order(quantity=10)
        _expect_failure(
            oms.StateMachine.transition(empty_id, oms.Event.Approve),
            oms.TransitionErrorCode.IllegalTransition,
        )

        zero_qty = oms.Order(order_id="ORD-2", quantity=0)
        _expect_failure(
            oms.StateMachine.transition(zero_qty, oms.Event.Approve),
            oms.TransitionErrorCode.IllegalTransition,
        )

        terminal = _make_order()
        terminal.status = oms.OrderStatus.Filled
        _expect_failure(
            oms.StateMachine.transition(terminal, oms.Event.Cancel),
            oms.TransitionErrorCode.TerminalState,
        )

    def test_all_legal_transitions_succeed(self) -> None:
        legal = [
            (oms.OrderStatus.PendingApproval, oms.Event.Approve, oms.OrderStatus.Approved, 0),
            (oms.OrderStatus.PendingApproval, oms.Event.Reject, oms.OrderStatus.Rejected, 0),
            (oms.OrderStatus.Approved, oms.Event.Submit, oms.OrderStatus.Submitted, 0),
            (oms.OrderStatus.Approved, oms.Event.Reject, oms.OrderStatus.Rejected, 0),
            (oms.OrderStatus.Submitted, oms.Event.Accept, oms.OrderStatus.Accepted, 0),
            (oms.OrderStatus.Submitted, oms.Event.Reject, oms.OrderStatus.Rejected, 0),
            (oms.OrderStatus.Submitted, oms.Event.Cancel, oms.OrderStatus.Cancelled, 0),
            (oms.OrderStatus.Submitted, oms.Event.Expire, oms.OrderStatus.Expired, 0),
            (oms.OrderStatus.Accepted, oms.Event.Cancel, oms.OrderStatus.Cancelled, 0),
            (oms.OrderStatus.Accepted, oms.Event.Expire, oms.OrderStatus.Expired, 0),
            (oms.OrderStatus.Accepted, oms.Event.Reject, oms.OrderStatus.Rejected, 0),
            (oms.OrderStatus.PartiallyFilled, oms.Event.Cancel, oms.OrderStatus.Cancelled, 0),
            (oms.OrderStatus.PartiallyFilled, oms.Event.Expire, oms.OrderStatus.Expired, 0),
        ]

        for from_status, event, to_status, fill_quantity in legal:
            order = _make_order()
            order.status = from_status
            result = oms.StateMachine.transition(order, event, fill_quantity)
            assert result.ok
            assert order.status == to_status

    def test_illegal_transitions_always_fail(self) -> None:
        illegal = [
            (oms.OrderStatus.PendingApproval, oms.Event.Submit),
            (oms.OrderStatus.PendingApproval, oms.Event.Accept),
            (oms.OrderStatus.Approved, oms.Event.Approve),
            (oms.OrderStatus.Submitted, oms.Event.Approve),
            (oms.OrderStatus.Submitted, oms.Event.PartialFill),
            (oms.OrderStatus.Accepted, oms.Event.Approve),
            (oms.OrderStatus.PartiallyFilled, oms.Event.Submit),
        ]

        for status, event in illegal:
            order = _make_order()
            order.status = status
            result = oms.StateMachine.transition(order, event, 10)
            assert not result.ok
            assert result.error.code == oms.TransitionErrorCode.IllegalTransition

        terminal_states = [
            oms.OrderStatus.Filled,
            oms.OrderStatus.Cancelled,
            oms.OrderStatus.Rejected,
            oms.OrderStatus.Expired,
        ]
        all_events = [
            oms.Event.Approve,
            oms.Event.Reject,
            oms.Event.Submit,
            oms.Event.Accept,
            oms.Event.PartialFill,
            oms.Event.Fill,
            oms.Event.Cancel,
            oms.Event.Expire,
        ]
        rng = np.random.default_rng(0x0A5342)
        for trial in range(200):
            order = _make_order(50)
            order.status = terminal_states[trial % len(terminal_states)]
            event = all_events[int(rng.integers(0, len(all_events)))]
            result = oms.StateMachine.transition(order, event, 1)
            assert not result.ok
            assert result.error.code == oms.TransitionErrorCode.TerminalState

    def test_numerical_stability_against_reference_literal(self) -> None:
        order = _make_order(100)
        order.status = oms.OrderStatus.Accepted
        result = oms.StateMachine.transition(order, oms.Event.PartialFill, REFERENCE_FILLED_QUANTITY)
        assert result.ok
        assert order.filled_quantity == REFERENCE_FILLED_QUANTITY
        assert result.order.filled_quantity == REFERENCE_FILLED_QUANTITY
        assert order.status == oms.OrderStatus.PartiallyFilled


class TestPositionTracker:
    def test_happy_path_hand_computed_net_position(self) -> None:
        tracker = oms.PositionTracker()
        assert tracker.apply_fill("SPY", 4000)
        assert tracker.apply_fill("SPY", 6000)
        assert tracker.leg_position("SPY") == 10000
        assert tracker.net_position() == 10000

    def test_empty_leg_id_rejected(self) -> None:
        tracker = oms.PositionTracker(5)
        assert not tracker.apply_fill("", 100)
        assert tracker.net_position() == 5

    def test_single_fill_updates_position(self) -> None:
        tracker = oms.PositionTracker()
        assert tracker.apply_fill("LEG-A", 1)
        assert tracker.leg_position("LEG-A") == 1
        assert tracker.net_position() == 1

    def test_concurrent_fills_produce_deterministic_position(self) -> None:
        tracker = oms.PositionTracker()

        def worker() -> None:
            for _ in range(CONCURRENT_FILL_COUNT):
                assert tracker.apply_fill("SPY", 1)

        threads = [threading.Thread(target=worker) for _ in range(CONCURRENT_THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert tracker.leg_position("SPY") == REFERENCE_NET_POSITION
        assert tracker.net_position() == REFERENCE_NET_POSITION

    def test_numerical_stability_against_reference_literal(self) -> None:
        tracker = oms.PositionTracker()
        deltas = np.ones(REFERENCE_NET_POSITION, dtype=np.int64)
        tracker.apply_fills("LIT", deltas)
        assert tracker.leg_position("LIT") == REFERENCE_NET_POSITION
        assert tracker.net_position() == REFERENCE_NET_POSITION
