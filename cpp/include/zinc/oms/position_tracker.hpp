/**
 * @file   position_tracker.hpp
 * @brief  Thread-safe multi-leg position tracker for zinc::oms.
 */

#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

namespace zinc::oms {

/**
 * @brief Thread-safe net position per leg using compare-and-swap updates.
 *
 * Each leg maintains an independent @c std::atomic&lt;int64_t&gt; position updated with a
 * CAS loop so concurrent partial fills converge deterministically.
 */
class PositionTracker {
  public:
    /**
     * @brief Construct a tracker with an optional initial net position.
     *
     * @param initial_net_position Starting aggregate position across all legs.
     */
    explicit PositionTracker(int64_t initial_net_position = 0);

    /**
     * @brief Apply a signed fill quantity to a leg and the aggregate net position.
     *
     * @param leg_id          Instrument or leg identifier (non-empty).
     * @param quantity_delta  Signed share delta (positive for buys, negative for sells).
     *
     * @return @c true when the update succeeds, @c false when @p leg_id is empty.
     *
     * @pre Concurrent calls for the same @p leg_id serialize via CAS.
     */
    [[nodiscard]] bool apply_fill(const std::string& leg_id, int64_t quantity_delta);

    /**
     * @brief Aggregate net position across all legs.
     */
    [[nodiscard]] int64_t net_position() const noexcept;

    /**
     * @brief Position for one leg (0 when unknown).
     *
     * @param leg_id Leg identifier.
     */
    [[nodiscard]] int64_t leg_position(const std::string& leg_id) const;

  private:
    struct LegState {
        std::atomic<int64_t> quantity{0};
    };

    [[nodiscard]] std::shared_ptr<LegState> leg_state(const std::string& leg_id);

    std::atomic<int64_t> net_position_;
    mutable std::mutex legs_mutex_;
    std::unordered_map<std::string, std::shared_ptr<LegState>> legs_;
};

}  // namespace zinc::oms
