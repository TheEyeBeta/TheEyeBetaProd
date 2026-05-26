/**
 * @file   adx.hpp
 * @brief  Average Directional Index (Wilder ADX).
 */

#pragma once

#include <cstddef>
#include <span>
#include <vector>

#include "zinc/ta/bar.hpp"

namespace zinc::ta {

/**
 * @brief Wilder Average Directional Index (ADX).
 *
 * Computes @f$+DI@f$, @f$-DI@f$, @f$DX@f$, then smooths @f$DX@f$ with Wilder RMA
 * to obtain ADX. Methodology matches pandas-ta / Wilder conventions.
 *
 * @param bars   Chronological OHLC bars.
 * @param period Smoothing window (@f$\ge 1@f$).
 *
 * @return ADX series aligned with @p bars (quiet_NaN during warmup).
 *
 * @pre @p period &ge; 1.
 *
 * @example
 * @code
 * const auto adx_values = zinc::ta::adx(bars, 14);
 * @endcode
 */
[[nodiscard]] std::vector<double> adx(std::span<const Bar> bars, int period);

}  // namespace zinc::ta
