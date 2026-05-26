/**
 * @file   order.cpp
 * @brief  Order helpers for zinc::oms.
 */

#include "zinc/oms/order.hpp"

namespace zinc::oms {

bool is_terminal(const OrderStatus status) noexcept {
    switch (status) {
        case OrderStatus::Filled:
        case OrderStatus::Cancelled:
        case OrderStatus::Rejected:
        case OrderStatus::Expired:
            return true;
        default:
            return false;
    }
}

}  // namespace zinc::oms
