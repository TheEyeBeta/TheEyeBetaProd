/**
 * @file   max_drawdown.hpp
 * @brief  Maximum peak-to-trough drawdown on a wealth or equity curve.
 */

#pragma once

#include <span>

namespace zinc::risk {

/**
 * @brief Maximum relative drawdown of a wealth (equity) series.
 *
 * For each point @f$W_t@f$, relative drawdown is
 * @f$(\max_{s \le t} W_s - W_t) / \max_{s \le t} W_s@f$.
 * Returns the maximum over @f$t@f$.
 *
 * @param wealth Strictly positive equity or portfolio value series (chronological).
 *
 * @return Maximum drawdown in @f$[0, 1]@f$, or quiet_NaN when undefined.
 *
 * @pre @p wealth is non-empty and all values are strictly positive for a finite result.
 *
 * @example
 * @code
 * const double curve[] = {100.0, 120.0, 90.0, 110.0};
 * const double mdd = zinc::risk::max_drawdown(curve);
 * // mdd = (120 - 90) / 120 = 0.25
 * @endcode
 */
[[nodiscard]] double max_drawdown(std::span<const double> wealth) noexcept;

}  // namespace zinc::risk
