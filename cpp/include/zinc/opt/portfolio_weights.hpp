/**
 * @file   portfolio_weights.hpp
 * @brief  Portfolio weight vector returned by zinc::opt kernels.
 */

#pragma once

#include <cstddef>
#include <vector>

namespace zinc::opt {

/**
 * @brief Long-only (or general) portfolio weights that sum to one.
 */
struct PortfolioWeights {
    /** @brief Asset weights aligned with input series / covariance dimension. */
    std::vector<double> weights;
};

} // namespace zinc::opt
