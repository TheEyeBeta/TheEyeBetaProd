/**
 * @file   cvar.cpp
 * @brief  Conditional Value-at-Risk implementation.
 */

#include "zinc/risk/cvar.hpp"

#include "zinc/risk/detail/quantile.hpp"

#include <limits>
#include <vector>

namespace zinc::risk {

double cvar(std::span<const double> samples, double alpha) noexcept {
    if (samples.empty() || !detail::valid_alpha(alpha)) {
        return std::numeric_limits<double>::quiet_NaN();
    }
    if (samples.size() == 1) {
        return samples.front();
    }

    std::vector<double> work(samples.begin(), samples.end());
    const double threshold = detail::nth_lower_quantile(work, alpha);
    return detail::tail_mean(samples, threshold);
}

} // namespace zinc::risk
