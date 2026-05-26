/**
 * @file   zscore.cpp
 * @brief  Rolling z-score implementation.
 */

#include "zinc/ta/zscore.hpp"

#include <cmath>
#include <cstddef>
#include <limits>
#include <span>

#include "zinc/ta/detail/wilder.hpp"

namespace zinc::ta {

std::vector<double> zscore(std::span<const double> series, int period) {
    const std::size_t length = series.size();
    if (length == 0 || period < 1) {
        return {};
    }

    auto output = detail::nan_series(length);
    if (length < static_cast<std::size_t>(period)) {
        return output;
    }

    for (std::size_t index = static_cast<std::size_t>(period - 1); index < length; ++index) {
        const std::span<const double> window =
            series.subspan(index - static_cast<std::size_t>(period - 1),
                           static_cast<std::size_t>(period));
        const double mean = detail::rolling_mean(window);
        const double std_dev = detail::rolling_std_population(window, mean);
        if (std_dev == 0.0) {
            output[index] = 0.0;
        } else {
            output[index] = (series[index] - mean) / std_dev;
        }
    }

    return output;
}

}  // namespace zinc::ta
