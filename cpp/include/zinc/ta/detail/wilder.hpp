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

    for (std::size_t start = 0; start + static_cast<std::size_t>(period) <= length; ++start) {
        double seed = 0.0;
        bool finite_window = true;
        for (int offset = 0; offset < period; ++offset) {
            const double value = values[start + static_cast<std::size_t>(offset)];
            if (!std::isfinite(value)) {
                finite_window = false;
                break;
            }
            seed += value;
        }
        if (!finite_window) {
            continue;
        }

        const std::size_t seed_index = start + static_cast<std::size_t>(period - 1);
        seed /= static_cast<double>(period);
        output[seed_index] = seed;

        for (std::size_t index = seed_index + 1; index < length; ++index) {
            if (!std::isfinite(values[index])) {
                continue;
            }
            seed = (seed * static_cast<double>(period - 1) + values[index]) /
                   static_cast<double>(period);
            output[index] = seed;
        }
        break;
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
