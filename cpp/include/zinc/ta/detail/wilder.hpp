/**
 * @file   wilder.hpp
 * @brief  Wilder smoothing (RMA) helpers for TA indicators.
 */

#pragma once

#include <cmath>
#include <cstddef>
#include <limits>
#include <span>
#include <vector>

namespace zinc::ta::detail {

inline std::vector<double> nan_series(std::size_t length) {
    return std::vector<double>(length, std::numeric_limits<double>::quiet_NaN());
}

/**
 * @brief Wilder's smoothed moving average (RMA) with pandas-ta-compatible seeding.
 *
 * The first finite value at index @c period-1 is the simple mean of the first
 * @p period samples; subsequent values use
 * @f$ \mathrm{RMA}_t = (\mathrm{RMA}_{t-1}\cdot(p-1) + x_t)/p @f$.
 */
inline std::vector<double> wilder_rma(std::span<const double> values, int period) {
    const std::size_t length = values.size();
    auto output = nan_series(length);
    if (period < 1 || length < static_cast<std::size_t>(period)) {
        return output;
    }

    double seed = 0.0;
    for (int index = 0; index < period; ++index) {
        seed += values[static_cast<std::size_t>(index)];
    }
    seed /= static_cast<double>(period);
    output[static_cast<std::size_t>(period - 1)] = seed;

    for (std::size_t index = static_cast<std::size_t>(period); index < length; ++index) {
        seed =
            (seed * static_cast<double>(period - 1) + values[index]) / static_cast<double>(period);
        output[index] = seed;
    }

    return output;
}

inline double rolling_mean(std::span<const double> window) {
    double sum = 0.0;
    for (const double value : window) {
        sum += value;
    }
    return sum / static_cast<double>(window.size());
}

inline double rolling_std_population(std::span<const double> window, double mean) {
    double sum_sq = 0.0;
    for (const double value : window) {
        const double delta = value - mean;
        sum_sq += delta * delta;
    }
    return std::sqrt(sum_sq / static_cast<double>(window.size()));
}

} // namespace zinc::ta::detail
