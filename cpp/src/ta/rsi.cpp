/**
 * @file   rsi.cpp
 * @brief  Wilder RSI implementation.
 */

#include "zinc/ta/rsi.hpp"

#include "zinc/ta/detail/wilder.hpp"

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

namespace zinc::ta {

std::vector<double> rsi(std::span<const Bar> bars, int period) {
    const std::size_t length = bars.size();
    auto output = detail::nan_series(length);
    if (period < 1 || length < 2) {
        return output;
    }

    std::vector<double> gains(length, 0.0);
    std::vector<double> losses(length, 0.0);
    for (std::size_t index = 1; index < length; ++index) {
        const double delta = bars[index].close - bars[index - 1].close;
        if (delta > 0.0) {
            gains[index] = delta;
        } else if (delta < 0.0) {
            losses[index] = -delta;
        }
    }

    const auto avg_gain = detail::wilder_rma(gains, period);
    const auto avg_loss = detail::wilder_rma(losses, period);

    for (std::size_t index = 0; index < length; ++index) {
        const double loss = avg_loss[index];
        const double gain = avg_gain[index];
        if (!std::isfinite(gain) || !std::isfinite(loss)) {
            continue;
        }
        if (loss == 0.0) {
            output[index] = gain > 0.0 ? 100.0 : 50.0;
            continue;
        }
        const double rs = gain / loss;
        output[index] = 100.0 - (100.0 / (1.0 + rs));
    }

    return output;
}

} // namespace zinc::ta
