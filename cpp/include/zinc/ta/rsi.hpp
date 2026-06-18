/**
 * @file   rsi.hpp
 * @brief  Relative Strength Index (Wilder RSI).
 */

#pragma once

#include "zinc/ta/bar.hpp"

#include <span>
#include <vector>

namespace zinc::ta {

/**
 * @brief Wilder RSI over OHLC bars (uses close prices).
 *
 * @param bars   Chronological OHLC bars.
 * @param period Smoothing window (@f$\ge 1@f$).
 * @return RSI series aligned with @p bars; values in [0, 100] when defined.
 */
[[nodiscard]] std::vector<double> rsi(std::span<const Bar> bars, int period);

} // namespace zinc::ta
