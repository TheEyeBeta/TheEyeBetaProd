/**
 * @file   bollinger.hpp
 * @brief  Bollinger Bands.
 */

#pragma once

#include <cstddef>
#include <span>
#include <vector>

namespace zinc::ta {

/**
 * @brief Bollinger Bands (SMA middle, population-std envelopes).
 */
struct BollingerBands {
    std::vector<double> lower;
    std::vector<double> middle;
    std::vector<double> upper;
};

/**
 * @brief Bollinger Bands around a rolling simple moving average.
 *
 * @f[
 *   \mathrm{middle}_t = \mathrm{SMA}_t,\quad
 *   \mathrm{upper}_t = \mathrm{middle}_t + k\sigma_t,\quad
 *   \mathrm{lower}_t = \mathrm{middle}_t - k\sigma_t
 * @f]
 *
 * @param series   Input series (typically close).
 * @param period   SMA / std window (@f$\ge 1@f$).
 * @param std_dev  Band width multiplier (default @c 2.0).
 *
 * @return Lower, middle, and upper band series aligned with @p series.
 *
 * @pre @p period &ge; 1 and @p std_dev &gt; 0.
 *
 * @example
 * @code
 * const auto bands = zinc::ta::bollinger(closes, 20, 2.0);
 * @endcode
 */
[[nodiscard]] BollingerBands bollinger(std::span<const double> series, int period,
                                       double std_dev = 2.0);

}  // namespace zinc::ta
