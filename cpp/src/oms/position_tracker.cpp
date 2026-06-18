/**
 * @file   position_tracker.cpp
 * @brief  Thread-safe multi-leg position tracker implementation.
 */

#include "zinc/oms/position_tracker.hpp"

#include <utility>

namespace zinc::oms {

PositionTracker::PositionTracker(const int64_t initial_net_position)
    : net_position_(initial_net_position) {}

std::shared_ptr<PositionTracker::LegState> PositionTracker::leg_state(const std::string& leg_id) {
    {
        const std::lock_guard<std::mutex> lock(legs_mutex_);
        const auto found = legs_.find(leg_id);
        if (found != legs_.end()) {
            return found->second;
        }
    }

    auto state = std::make_shared<LegState>();
    {
        const std::lock_guard<std::mutex> lock(legs_mutex_);
        const auto [iterator, inserted] = legs_.emplace(leg_id, state);
        return inserted ? state : iterator->second;
    }
}

bool PositionTracker::apply_fill(const std::string& leg_id, const int64_t quantity_delta) {
    if (leg_id.empty()) {
        return false;
    }

    const std::shared_ptr<LegState> leg = leg_state(leg_id);
    int64_t current = leg->quantity.load(std::memory_order_relaxed);
    while (!leg->quantity.compare_exchange_weak(
        current, current + quantity_delta, std::memory_order_acq_rel, std::memory_order_relaxed)) {
    }

    int64_t net = net_position_.load(std::memory_order_relaxed);
    while (!net_position_.compare_exchange_weak(
        net, net + quantity_delta, std::memory_order_acq_rel, std::memory_order_relaxed)) {
    }

    return true;
}

int64_t PositionTracker::net_position() const noexcept {
    return net_position_.load(std::memory_order_acquire);
}

int64_t PositionTracker::leg_position(const std::string& leg_id) const {
    const std::lock_guard<std::mutex> lock(legs_mutex_);
    const auto found = legs_.find(leg_id);
    if (found == legs_.end()) {
        return 0;
    }
    return found->second->quantity.load(std::memory_order_acquire);
}

} // namespace zinc::oms
