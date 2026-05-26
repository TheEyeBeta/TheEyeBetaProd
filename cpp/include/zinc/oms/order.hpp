/**
 * @file   order.hpp
 * @brief  Order model shared by zinc::oms kernels.
 */

#pragma once

#include <cstdint>
#include <string>

namespace zinc::oms {

/**
 * @brief Lifecycle status of an order in the OMS.
 */
enum class OrderStatus {
    PendingApproval,
    Approved,
    Submitted,
    Accepted,
    PartiallyFilled,
    Filled,
    Cancelled,
    Rejected,
    Expired,
};

/**
 * @brief Domain events that drive order state transitions.
 */
enum class Event {
    Approve,
    Reject,
    Submit,
    Accept,
    PartialFill,
    Fill,
    Cancel,
    Expire,
};

/**
 * @brief Error code returned when a transition is not permitted.
 */
enum class TransitionErrorCode {
    /** @brief Event is not valid for the current status. */
    IllegalTransition,

    /** @brief Order is already in a terminal status. */
    TerminalState,

    /** @brief Fill quantity is non-positive or exceeds remaining quantity. */
    InvalidFillQuantity,
};

/**
 * @brief Detailed transition failure information.
 */
struct TransitionError {
    TransitionErrorCode code = TransitionErrorCode::IllegalTransition;
    OrderStatus from_status = OrderStatus::PendingApproval;
    Event event = Event::Approve;
};

/**
 * @brief Order record mutated by the state machine.
 */
struct Order {
    /** @brief Client-supplied identifier (non-empty for active orders). */
    std::string order_id;

    /** @brief Current lifecycle status. */
    OrderStatus status = OrderStatus::PendingApproval;

    /** @brief Target order quantity in shares (must be &gt; 0). */
    int64_t quantity = 0;

    /** @brief Cumulative filled quantity in shares. */
    int64_t filled_quantity = 0;
};

/**
 * @brief Returns true when @p status is terminal (no further transitions).
 */
[[nodiscard]] bool is_terminal(OrderStatus status) noexcept;

}  // namespace zinc::oms
