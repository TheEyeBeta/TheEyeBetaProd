/**
 * @file   state_machine.cpp
 * @brief  Order lifecycle state machine implementation.
 */

#include "zinc/oms/state_machine.hpp"

namespace zinc::oms {

namespace {

TransitionError make_error(const TransitionErrorCode code, const OrderStatus from_status,
                           const Event event) {
    return TransitionError{.code = code, .from_status = from_status, .event = event};
}

bool apply_fill(Order& order, const int64_t fill_quantity, const bool force_complete) {
    if (fill_quantity <= 0 && !force_complete) {
        return false;
    }

    const int64_t increment =
        force_complete ? order.quantity - order.filled_quantity : fill_quantity;
    if (increment <= 0 || order.filled_quantity + increment > order.quantity) {
        return false;
    }

    order.filled_quantity += increment;
    if (order.filled_quantity >= order.quantity) {
        order.filled_quantity = order.quantity;
        order.status = OrderStatus::Filled;
    } else {
        order.status = OrderStatus::PartiallyFilled;
    }
    return true;
}

}  // namespace

expected<Order, TransitionError> StateMachine::transition(Order& order, const Event event,
                                                          const int64_t fill_quantity) {
    if (order.order_id.empty() || order.quantity <= 0) {
        return unexpected(
            make_error(TransitionErrorCode::IllegalTransition, order.status, event));
    }

    if (is_terminal(order.status)) {
        return unexpected(
            make_error(TransitionErrorCode::TerminalState, order.status, event));
    }

    const OrderStatus from_status = order.status;

    switch (order.status) {
        case OrderStatus::PendingApproval:
            if (event == Event::Approve) {
                order.status = OrderStatus::Approved;
                return order;
            }
            if (event == Event::Reject) {
                order.status = OrderStatus::Rejected;
                return order;
            }
            break;

        case OrderStatus::Approved:
            if (event == Event::Submit) {
                order.status = OrderStatus::Submitted;
                return order;
            }
            if (event == Event::Reject) {
                order.status = OrderStatus::Rejected;
                return order;
            }
            break;

        case OrderStatus::Submitted:
            if (event == Event::Accept) {
                order.status = OrderStatus::Accepted;
                return order;
            }
            if (event == Event::Reject) {
                order.status = OrderStatus::Rejected;
                return order;
            }
            if (event == Event::Cancel) {
                order.status = OrderStatus::Cancelled;
                return order;
            }
            if (event == Event::Expire) {
                order.status = OrderStatus::Expired;
                return order;
            }
            break;

        case OrderStatus::Accepted:
            if (event == Event::PartialFill) {
                if (!apply_fill(order, fill_quantity, false)) {
                    return unexpected(make_error(TransitionErrorCode::InvalidFillQuantity,
                                                   from_status, event));
                }
                return order;
            }
            if (event == Event::Fill) {
                if (!apply_fill(order, fill_quantity, fill_quantity <= 0)) {
                    return unexpected(make_error(TransitionErrorCode::InvalidFillQuantity,
                                                   from_status, event));
                }
                return order;
            }
            if (event == Event::Cancel) {
                order.status = OrderStatus::Cancelled;
                return order;
            }
            if (event == Event::Expire) {
                order.status = OrderStatus::Expired;
                return order;
            }
            if (event == Event::Reject) {
                order.status = OrderStatus::Rejected;
                return order;
            }
            break;

        case OrderStatus::PartiallyFilled:
            if (event == Event::PartialFill) {
                if (!apply_fill(order, fill_quantity, false)) {
                    return unexpected(make_error(TransitionErrorCode::InvalidFillQuantity,
                                                   from_status, event));
                }
                return order;
            }
            if (event == Event::Fill) {
                if (!apply_fill(order, fill_quantity, fill_quantity <= 0)) {
                    return unexpected(make_error(TransitionErrorCode::InvalidFillQuantity,
                                                   from_status, event));
                }
                return order;
            }
            if (event == Event::Cancel) {
                order.status = OrderStatus::Cancelled;
                return order;
            }
            if (event == Event::Expire) {
                order.status = OrderStatus::Expired;
                return order;
            }
            break;

        default:
            break;
    }

    return unexpected(make_error(TransitionErrorCode::IllegalTransition, from_status, event));
}

}  // namespace zinc::oms
