/**
 * @file   historical_var.hpp
 * @brief  Historical simulation Value-at-Risk for a return or P&amp;L sample.
 */

#pragma once

#include <span>

namespace zinc::risk {

/**
 * @brief Historical (non-parametric) lower-tail Value-at-Risk.
 *
 * Computes the nearest-rank @f$\alpha@f$-quantile of @p samples in ascending order
 * using `std::nth_element` (linear average time). For a return series this is the
 * loss threshold such that at most a fraction @f$\alpha@f$ of observations lie below
 * it (left tail).
 *
 * @param samples Historical returns or P&amp;L observations (any order).
 * @param alpha   Tail probability in @f$(0, 1)@f$ (e.g. @c 0.05 for 95% VaR).
 *
 * @return The empirical @f$\alpha@f$-quantile, or quiet_NaN when undefined.
 *
 * @pre @p samples is non-empty and @p alpha &isin; (0, 1) for a finite result.
 *
 * @example
 * @code
 * const double returns[] = {-0.03, -0.01, 0.0, 0.01, 0.02};
 * const double var = zinc::risk::historical_var(returns, 0.20);
 * // var ≈ -0.01 (20th percentile)
 * @endcode
 */
[[nodiscard]] double historical_var(std::span<const double> samples, double alpha) noexcept;

} // namespace zinc::risk
