/**
 * @file   snapshot_technicals.hpp
 * @brief  Batch last-bar technical indicators for snapshot packaging.
 */

#pragma once

#include "zinc/ta/bar.hpp"

#include <cstddef>
#include <limits>
#include <span>
#include <vector>

namespace zinc::ta {

/** Last-bar technical values for one instrument. */
struct TechnicalsLast {
    double atr14 = std::numeric_limits<double>::quiet_NaN();
    double adx14 = std::numeric_limits<double>::quiet_NaN();
    double rsi14 = std::numeric_limits<double>::quiet_NaN();
    double zscore20 = std::numeric_limits<double>::quiet_NaN();
    double bb_upper20_2 = std::numeric_limits<double>::quiet_NaN();
    double bb_lower20_2 = std::numeric_limits<double>::quiet_NaN();
};

/**
 * @brief Compute snapshot technicals for many instruments without Python loops.
 *
 * @param ohlc_by_instrument Each span is chronological OHLC bars for one symbol.
 */
[[nodiscard]] std::vector<TechnicalsLast>
snapshot_technicals_last(std::span<const std::span<const Bar>> ohlc_by_instrument);

} // namespace zinc::ta
