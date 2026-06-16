/**
 * @file   _zinc_oms.cpp
 * @brief  nanobind bindings for zinc::oms kernels.
 */

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>

#include <cstdint>

#include "zinc/oms/order.hpp"
#include "zinc/oms/position_tracker.hpp"
#include "zinc/oms/state_machine.hpp"

namespace nb = nanobind;

namespace {

using ContiguousInt64Vector = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig>;

/**
 * @brief Python-facing result of a state-machine transition.
 */
struct TransitionResult {
    bool ok = false;
    zinc::oms::Order order;
    zinc::oms::TransitionError error;
};

TransitionResult transition_order(zinc::oms::Order& order, const zinc::oms::Event event,
                                  const std::int64_t fill_quantity) {
    const zinc::oms::expected<zinc::oms::Order, zinc::oms::TransitionError> result =
        zinc::oms::StateMachine::transition(order, event, fill_quantity);
    if (result.has_value()) {
        return TransitionResult{.ok = true, .order = result.value(), .error = {}};
    }
    return TransitionResult{.ok = false, .order = order, .error = result.error()};
}

void apply_fills_ndarray(zinc::oms::PositionTracker& tracker, const std::string& leg_id,
                         const ContiguousInt64Vector& deltas) {
    if (deltas.ndim() != 1) {
        throw std::invalid_argument("deltas must be a one-dimensional int64 array");
    }
    for (std::size_t index = 0; index < deltas.shape(0); ++index) {
        if (!tracker.apply_fill(leg_id, deltas.data()[index])) {
            throw std::invalid_argument("leg_id must be non-empty");
        }
    }
}

}  // namespace

NB_MODULE(_zinc_oms, module) {
    module.doc() = "zinc::oms — order state machine and thread-safe position tracking";

    nb::enum_<zinc::oms::OrderStatus>(module, "OrderStatus", "Lifecycle status of an order in the OMS.")
        .value("PendingApproval", zinc::oms::OrderStatus::PendingApproval)
        .value("Approved", zinc::oms::OrderStatus::Approved)
        .value("Submitted", zinc::oms::OrderStatus::Submitted)
        .value("Accepted", zinc::oms::OrderStatus::Accepted)
        .value("PartiallyFilled", zinc::oms::OrderStatus::PartiallyFilled)
        .value("Filled", zinc::oms::OrderStatus::Filled)
        .value("Cancelled", zinc::oms::OrderStatus::Cancelled)
        .value("Rejected", zinc::oms::OrderStatus::Rejected)
        .value("Expired", zinc::oms::OrderStatus::Expired);

    nb::enum_<zinc::oms::Event>(module, "Event", "Domain events that drive order state transitions.")
        .value("Approve", zinc::oms::Event::Approve)
        .value("Reject", zinc::oms::Event::Reject)
        .value("Submit", zinc::oms::Event::Submit)
        .value("Accept", zinc::oms::Event::Accept)
        .value("PartialFill", zinc::oms::Event::PartialFill)
        .value("Fill", zinc::oms::Event::Fill)
        .value("Cancel", zinc::oms::Event::Cancel)
        .value("Expire", zinc::oms::Event::Expire);

    nb::enum_<zinc::oms::TransitionErrorCode>(module, "TransitionErrorCode",
                                              "Error code returned when a transition is not permitted.")
        .value("IllegalTransition", zinc::oms::TransitionErrorCode::IllegalTransition)
        .value("TerminalState", zinc::oms::TransitionErrorCode::TerminalState)
        .value("InvalidFillQuantity", zinc::oms::TransitionErrorCode::InvalidFillQuantity);

    nb::class_<zinc::oms::TransitionError>(module, "TransitionError",
                                           "Detailed transition failure information.")
        .def_ro("code", &zinc::oms::TransitionError::code)
        .def_ro("from_status", &zinc::oms::TransitionError::from_status)
        .def_ro("event", &zinc::oms::TransitionError::event);

    nb::class_<zinc::oms::Order>(module, "Order", "Order record mutated by the state machine.")
        .def(nb::init<>())
        .def_rw("order_id", &zinc::oms::Order::order_id,
                "Client-supplied identifier (non-empty for active orders).")
        .def_rw("status", &zinc::oms::Order::status, "Current lifecycle status.")
        .def_rw("quantity", &zinc::oms::Order::quantity, "Target order quantity in shares.")
        .def_rw("filled_quantity", &zinc::oms::Order::filled_quantity,
                "Cumulative filled quantity in shares.");

    nb::class_<TransitionResult>(module, "TransitionResult",
                                 "Outcome of a state-machine transition attempt.")
        .def_ro("ok", &TransitionResult::ok, "True when the transition succeeded.")
        .def_ro("order", &TransitionResult::order, "Order after the transition attempt.")
        .def_ro("error", &TransitionResult::error, "Error details when ok is false.");

    nb::class_<zinc::oms::StateMachine>(module, "StateMachine",
                                        "Finite-state machine for order lifecycle transitions.")
        .def_static(
            "transition", &transition_order, nb::arg("order"), nb::arg("event"),
            nb::arg("fill_quantity") = 0,
            "Apply an event to an order and return a TransitionResult.");

    nb::class_<zinc::oms::PositionTracker>(
        module, "PositionTracker",
        "Thread-safe net position per leg using compare-and-swap updates.")
        .def(nb::init<std::int64_t>(), nb::arg("initial_net_position") = 0,
             "Construct a tracker with an optional initial net position.")
        .def("apply_fill", &zinc::oms::PositionTracker::apply_fill, nb::arg("leg_id"),
             nb::arg("quantity_delta"),
             "Apply a signed fill quantity to a leg and the aggregate net position.")
        .def("apply_fills", &apply_fills_ndarray, nb::arg("leg_id"), nb::arg("deltas"),
             "Apply multiple signed fill deltas from a C-contiguous int64 ndarray.")
        .def("net_position", &zinc::oms::PositionTracker::net_position,
             "Aggregate net position across all legs.")
        .def("leg_position", &zinc::oms::PositionTracker::leg_position, nb::arg("leg_id"),
             "Position for one leg (0 when unknown).");

    module.def("is_terminal", &zinc::oms::is_terminal, nb::arg("status"),
               "Returns true when status is terminal (no further transitions).");
}
