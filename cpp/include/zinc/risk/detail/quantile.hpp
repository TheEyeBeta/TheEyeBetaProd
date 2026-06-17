/**
 * @file   quantile.hpp
 * @brief  Internal order-statistic helpers for zinc::risk (not part of the public API).
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <vector>

namespace zinc::risk::detail {

/// @returns true when @p alpha is a valid open-interval tail probability.
inline constexpr bool valid_alpha(double alpha) noexcept {
    return alpha > 0.0 && alpha < 1.0;
}

/**
 * @brief Nearest-rank index for the lower @p alpha quantile (0-based, ascending order).
 *
 * Uses @f$ k = \lceil \alpha n \rceil - 1 @f$ clamped to @f$[0, n-1]@f$.
 */
inline std::size_t lower_quantile_index(std::size_t count, double alpha) noexcept {
    if (count == 0) {
        return 0;
    }
    const auto rank = static_cast<std::size_t>(std::ceil(alpha * static_cast<double>(count)));
    return rank == 0 ? 0 : rank - 1;
}

/**
 * @brief In-place @f$\alpha@f$-quantile via `std::nth_element` (average O(n)).
 *
 * @param work Mutable copy of samples; reordered on return.
 */
inline double nth_lower_quantile(std::vector<double>& work, double alpha) {
    const std::size_t index = lower_quantile_index(work.size(), alpha);
    std::nth_element(work.begin(), work.begin() + static_cast<std::ptrdiff_t>(index), work.end());
    return work[index];
}

/**
 * @brief Mean of values less than or equal to @p threshold.
 *
 * @returns quiet_NaN when no samples satisfy the tail predicate.
 */
inline double tail_mean(std::span<const double> samples, double threshold) noexcept {
    double sum = 0.0;
    std::size_t count = 0;
    for (const double value : samples) {
        if (value <= threshold) {
            sum += value;
            ++count;
        }
    }
    if (count == 0) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    return sum / static_cast<double>(count);
}

} // namespace zinc::risk::detail
