/**
 * @file   mvo.hpp
 * @brief  Mean–variance (Markowitz) portfolio optimization.
 */

#pragma once

#include "zinc/opt/portfolio_weights.hpp"

#include <Eigen/Dense>

namespace zinc::opt {

/**
 * @brief Long-only mean–variance optimal portfolio (Markowitz).
 *
 * Maximizes @f$\mu^\top w - \frac{\lambda}{2} w^\top \Sigma w@f$ subject to
 * @f$\mathbf{1}^\top w = 1@f$ and @f$w \ge 0@f$ (when @p long_only is true).
 * Uses projected gradient ascent with simplex projection.
 *
 * @param expected_returns Expected excess returns (@f$n@f$).
 * @param covariance     Covariance matrix (@f$n \times n@f$, positive semi-definite).
 * @param risk_aversion  Risk-aversion parameter @f$\lambda@f$ (@f$> 0@f$).
 * @param long_only      If true, enforce non-negative weights (default).
 *
 * @return Portfolio weights summing to @c 1.0, or empty on invalid input.
 *
 * @pre @p expected_returns.size() matches @p covariance.rows() and @f$\lambda > 0@f$.
 *
 * @example
 * @code
 * Eigen::Vector2d mu(0.10, 0.05);
 * Eigen::Matrix2d cov;
 * cov << 0.04, 0.01, 0.01, 0.09;
 * const auto weights = zinc::opt::mvo(mu, cov, 1.0);
 * @endcode
 */
[[nodiscard]] PortfolioWeights mvo(const Eigen::Ref<const Eigen::VectorXd>& expected_returns,
                                   const Eigen::Ref<const Eigen::MatrixXd>& covariance,
                                   double risk_aversion = 1.0, bool long_only = true);

} // namespace zinc::opt
