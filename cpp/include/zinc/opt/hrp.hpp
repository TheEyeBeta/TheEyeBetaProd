/**
 * @file   hrp.hpp
 * @brief  Hierarchical Risk Parity (HRP) portfolio weights.
 */

#pragma once

#include <Eigen/Dense>

#include "zinc/opt/portfolio_weights.hpp"

namespace zinc::opt {

/**
 * @brief Hierarchical Risk Parity weights via recursive bisection.
 *
 * Builds a correlation-distance linkage tree, quasi-diagonalizes the covariance,
 * then allocates mass recursively between clusters inversely to cluster variance
 * (inverse-variance intra-cluster weights). Weights are long-only and sum to one.
 *
 * @param covariance Covariance matrix (@f$n \times n@f$, positive semi-definite).
 *
 * @return Portfolio weights summing to @c 1.0, or empty on invalid input.
 *
 * @pre @p covariance is square with @f$n \ge 1@f$.
 *
 * @example
 * @code
 * Eigen::Matrix2d cov;
 * cov << 0.04, 0.0, 0.0, 0.09;
 * const auto weights = zinc::opt::hrp(cov);
 * @endcode
 */
[[nodiscard]] PortfolioWeights hrp(const Eigen::Ref<const Eigen::MatrixXd>& covariance);

}  // namespace zinc::opt
