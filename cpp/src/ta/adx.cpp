/**
 * @file   adx.cpp
 * @brief  Average Directional Index implementation.
 */

#include "zinc/ta/adx.hpp"

#include "zinc/ta/detail/wilder.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <span>
#include <vector>

namespace zinc::ta {

std::vector<double> adx(std::span<const Bar> bars, int period) {
    const std::size_t length = bars.size();
    if (length == 0 || period < 1) {
        return {};
    }

    std::vector<double> true_ranges(length, 0.0);
    std::vector<double> plus_dm(length, 0.0);
    std::vector<double> minus_dm(length, 0.0);

    true_ranges[0] = bars[0].high - bars[0].low;
    for (std::size_t index = 1; index < length; ++index) {
        const Bar& current = bars[index];
        const Bar& previous = bars[index - 1];

        const double up_move = current.high - previous.high;
        const double down_move = previous.low - current.low;
        plus_dm[index] = (up_move > down_move && up_move > 0.0) ? up_move : 0.0;
        minus_dm[index] = (down_move > up_move && down_move > 0.0) ? down_move : 0.0;

        const double high_low = current.high - current.low;
        const double high_close = std::abs(current.high - previous.close);
        const double low_close = std::abs(current.low - previous.close);
        true_ranges[index] = std::max({high_low, high_close, low_close});
    }

    const std::vector<double> smoothed_tr = detail::wilder_rma(true_ranges, period);
    const std::vector<double> smoothed_plus = detail::wilder_rma(plus_dm, period);
    const std::vector<double> smoothed_minus = detail::wilder_rma(minus_dm, period);

    std::vector<double> dx = detail::nan_series(length);
    for (std::size_t index = 0; index < length; ++index) {
        if (!std::isfinite(smoothed_tr[index]) || smoothed_tr[index] == 0.0) {
            continue;
        }
        const double plus_di = 100.0 * smoothed_plus[index] / smoothed_tr[index];
        const double minus_di = 100.0 * smoothed_minus[index] / smoothed_tr[index];
        const double denominator = plus_di + minus_di;
        if (denominator == 0.0) {
            continue;
        }
        dx[index] = 100.0 * std::abs(plus_di - minus_di) / denominator;
    }

    return detail::wilder_rma(dx, period);
}

} // namespace zinc::ta
