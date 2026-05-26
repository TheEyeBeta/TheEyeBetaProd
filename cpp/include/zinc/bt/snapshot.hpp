/**
 * @file   snapshot.hpp
 * @brief  Point-in-time market view passed to the strategy callback.
 */

#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace zinc::bt {

/**
 * @brief One trading day's cross-section for the configured universe.
 *
 * Numeric fields are contiguous spans over the active symbols for the day.
 * String symbols are stored in @c symbol_names for stable lifetime during the callback.
 */
struct Snapshot {
    /** @brief ISO date @c YYYY-MM-DD for this tick. */
    std::string trade_date;

    /** @brief Zero-based index of this day in the backtest calendar. */
    int day_index = 0;

    /** @brief Symbols aligned with the numeric spans (same ordering). */
    std::vector<std::string> symbol_names;

    /** @brief Unadjusted closing prices. */
    std::span<const double> close;

    /** @brief 14-period ATR used for slippage (must be &gt; 0 when trading). */
    std::span<const double> atr14;

    /** @brief Average daily volume in shares for participation. */
    std::span<const double> adv;

    /** @brief Share volume on the trade date. */
    std::span<const int64_t> volume;
};

}  // namespace zinc::bt
