/**
 * @file   bollinger.cpp
 * @brief  Bollinger Bands implementation.
 */

#include "zinc/ta/bollinger.hpp"

#include <cmath>
#include <cstddef>
#include <limits>
#include <span>

#include "zinc/ta/detail/wilder.hpp"

namespace zinc::ta {

BollingerBands bollinger(std::span<const double> series, int period, double std_dev) {
    const std::size_t length = series.size();
    BollingerBands bands;
    if (length == 0 || period < 1 || std_dev <= 0.0) {
        return bands;
    }

    bands.lower = detail::nan_series(length);
    bands.middle = detail::nan_series(length);
    bands.upper = detail::nan_series(length);

    if (length < static_cast<std::size_t>(period)) {
        return bands;
    }

    for (std::size_t index = static_cast<std::size_t>(period - 1); index < length; ++index) {
        const std::span<const double> window =
            series.subspan(index - static_cast<std::size_t>(period - 1),
                           static_cast<std::size_t>(period));
        const double mean = detail::rolling_mean(window);
        const double sigma = detail::rolling_std_population(window, mean);
        bands.middle[index] = mean;
        bands.upper[index] = mean + std_dev * sigma;
        bands.lower[index] = mean - std_dev * sigma;
    }

    return bands;
}

}  // namespace zinc::ta
