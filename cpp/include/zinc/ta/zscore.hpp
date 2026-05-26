/**
 * @file   zscore.hpp
 * @brief  Rolling z-score.
 */

#pragma once

#include <cstddef>
#include <span>
#include <vector>

namespace zinc::ta {

/**
 * @brief Rolling z-score @f$(x_t - \mu_t)/\sigma_t@f$ over a fixed window.
 *
 * Uses population standard deviation (ddof=0) in the rolling window, consistent
 * with pandas-ta rolling z-score behaviour.
 *
 * @param series Rolling input series.
 * @param period Window length (@f$\ge 1@f$).
 *
 * @return Z-score series aligned with @p series.
 *
 * @pre @p period &ge; 1.
 *
 * @example
 * @code
 * const auto z = zinc::ta::zscore(closes, 20);
 * @endcode
 */
[[nodiscard]] std::vector<double> zscore(std::span<const double> series, int period);

}  // namespace zinc::ta
