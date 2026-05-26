/**
 * @file   state_machine.hpp
 * @brief  Order lifecycle state machine for zinc::oms.
 */

#pragma once

#include "zinc/oms/detail/expected.hpp"
#include "zinc/oms/order.hpp"

namespace zinc::oms {

/**
 * @brief Finite-state machine for order lifecycle transitions.
 *
 * Applies @p event to @p order when legal, updates @p order in place, and returns
 * the updated order on success.
 */
class StateMachine {
  public:
    /**
     * @brief Apply an event to an order.
     *
     * @param order          Order to transition (updated in place on success).
     * @param event          Domain event.
     * @param fill_quantity  Shares filled for @ref Event::PartialFill / @ref Event::Fill
     *                       (ignored for other events; must be &gt; 0 for fills).
     *
     * @return @c std::expected (or equivalent) with the updated order on success, or
     *         @ref TransitionError on failure.
     *
     * @pre @p order.quantity &gt; 0 for fill-related transitions.
     *
     * @example
     * @code
     * zinc::oms::Order order{.order_id = "o1", .quantity = 100};
     * auto result = zinc::oms::StateMachine::transition(order, zinc::oms::Event::Approve);
     * @endcode
     */
    [[nodiscard]] static expected<Order, TransitionError> transition(Order& order, Event event,
                                                                     int64_t fill_quantity = 0);
};

}  // namespace zinc::oms
