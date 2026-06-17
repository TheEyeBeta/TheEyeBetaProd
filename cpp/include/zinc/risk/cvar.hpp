/**
 * @file   cvar.hpp
 * @brief  Historical Conditional Value-at-Risk (Expected Shortfall).
 */

#pragma once

#include <span>

namespace zinc::risk {

/**
 * @brief Historical Conditional VaR (Expected Shortfall) in the lower tail.
 *
 * Let @f$q@f$ be the historical @f$\alpha@f$-quantile of @p samples. CVaR is the
 * arithmetic mean of all observations @f$\le q@f$ (inclusive), matching the
 * historical-simulation ES definition used with historical VaR.
 *
 * @param samples Historical returns or P&amp;L observations (any order).
 * @param alpha   Tail probability in @f$(0, 1)@f$.
 *
 * @return Tail mean, or quiet_NaN when undefined.
 *
 * @pre @p samples is non-empty and @p alpha &isin; (0, 1) for a finite result.
 *
 * @example
 * @code
 * const double losses[] = {-5.0, -3.0, -2.0, 0.0, 1.0};
 * const double es = zinc::risk::cvar(losses, 0.40);
 * // es = mean({-5, -3}) = -4.0
 * @endcode
 */
[[nodiscard]] double cvar(std::span<const double> samples, double alpha) noexcept;

} // namespace zinc::risk
