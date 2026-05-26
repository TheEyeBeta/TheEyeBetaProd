/**
 * @file   max_drawdown.cpp
 * @brief  Maximum drawdown implementation.
 */

#include "zinc/risk/max_drawdown.hpp"

#include <algorithm>
#include <limits>

namespace zinc::risk {

double max_drawdown(std::span<const double> wealth) noexcept {
    if (wealth.empty()) {
        return std::numeric_limits<double>::quiet_NaN();
    }

    double running_peak = wealth.front();
    if (!(running_peak > 0.0)) {
        return std::numeric_limits<double>::quiet_NaN();
    }

    double worst_drawdown = 0.0;
    for (const double value : wealth) {
        if (!(value > 0.0)) {
            return std::numeric_limits<double>::quiet_NaN();
        }
        running_peak = std::max(running_peak, value);
        const double drawdown = (running_peak - value) / running_peak;
        worst_drawdown = std::max(worst_drawdown, drawdown);
    }

    return worst_drawdown;
}

}  // namespace zinc::risk
