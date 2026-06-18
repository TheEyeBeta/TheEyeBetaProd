/**
 * @file   historical_var.cpp
 * @brief  Historical Value-at-Risk implementation.
 */

#include "zinc/risk/historical_var.hpp"

#include "zinc/risk/detail/quantile.hpp"

#include <limits>
#include <vector>

namespace zinc::risk {

double historical_var(std::span<const double> samples, double alpha) noexcept {
    if (samples.empty() || !detail::valid_alpha(alpha)) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    if (samples.size() == 1) {
        return samples.front();
    }

    std::vector<double> work(samples.begin(), samples.end());
    return detail::nth_lower_quantile(work, alpha);
}

} // namespace zinc::risk
