/**
 * @file   atr.cpp
 * @brief  Average True Range implementation.
 */

#include "zinc/ta/atr.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <span>

#include "zinc/ta/detail/wilder.hpp"

namespace zinc::ta {

namespace {

double true_range(const Bar& current, const Bar& previous, bool has_previous) {
    const double high_low = current.high - current.low;
    if (!has_previous) {
        return high_low;
    }
    const double high_close = std::abs(current.high - previous.close);
    const double low_close = std::abs(current.low - previous.close);
    return std::max({high_low, high_close, low_close});
}

}  // namespace

std::vector<double> atr(std::span<const Bar> bars, int period) {
    const std::size_t length = bars.size();
    if (length == 0 || period < 1) {
        return {};
    }

    std::vector<double> true_ranges(length);
    for (std::size_t index = 0; index < length; ++index) {
        true_ranges[index] = true_range(bars[index], bars[index > 0 ? index - 1 : 0], index > 0);
    }

    return detail::wilder_rma(true_ranges, period);
}

}  // namespace zinc::ta
