/**
 * @file   atr.hpp
 * @brief  Average True Range (Wilder ATR).
 */

#pragma once

#include <cstddef>
#include <span>
#include <vector>

#include "zinc/ta/bar.hpp"

namespace zinc::ta {

/**
 * @brief Wilder Average True Range over OHLC bars.
 *
 * True range is @f$\max(H-L, |H-C_{prev}|, |L-C_{prev}|)@f$; ATR applies Wilder
 * RMA with window @p period (pandas-ta compatible seeding).
 *
 * @param bars   Chronological OHLC bars.
 * @param period Smoothing window (@f$\ge 1@f$).
 *
 * @return Series aligned with @p bars; leading values are quiet_NaN until warmed up.
 *
 * @pre @p period &ge; 1 and @p bars is non-empty for finite tail values.
 *
 * @example
 * @code
 * const std::vector<Bar> bars = /* ... */;
 * const auto atr_values = zinc::ta::atr(bars, 14);
 * @endcode
 */
[[nodiscard]] std::vector<double> atr(std::span<const Bar> bars, int period);

}  // namespace zinc::ta
