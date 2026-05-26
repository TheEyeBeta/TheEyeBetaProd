/**
 * @file   black_litterman.hpp
 * @brief  Black–Litterman posterior weights via mean–variance optimization.
 */

#pragma once

#include <Eigen/Dense>

#include "zinc/opt/portfolio_weights.hpp"

namespace zinc::opt {

/**
 * @brief Black–Litterman optimal portfolio weights.
 *
 * Combines an equilibrium prior @f$\pi = \delta \Sigma w_{mkt}@f$ with investor views
 * @f$P\mu = Q@f$ (Gaussian, covariance @f$\Omega@f$) to obtain posterior expected
 * returns, then solves the same long-only MVO problem as @ref mvo.
 *
 * @param covariance        Asset covariance matrix (@f$n \times n@f$).
 * @param market_weights    Market-cap weights (@f$n@f$, sum to one).
 * @param picking_matrix    View picking matrix @f$P@f$ (@f$k \times n@f$).
 * @param view_returns      View expected returns @f$Q@f$ (@f$k@f$).
 * @param view_uncertainty  Diagonal view uncertainties @f$\omega@f$ (@f$k@f$, &gt; 0).
 * @param risk_aversion     Equilibrium risk-aversion @f$\delta@f$ (default @c 2.5).
 * @param tau             Prior scaling @f$\tau@f$ (default @c 0.05).
 * @param long_only         Enforce non-negative weights (default).
 *
 * @return Portfolio weights summing to @c 1.0, or empty on invalid input.
 *
 * @pre Dimensions are consistent and @p view_uncertainty entries are positive.
 *
 * @example
 * @code
 * Eigen::MatrixXd P(1, 2);
 * P << 1.0, 0.0;
 * const auto weights = zinc::opt::black_litterman(
 *     cov, market_weights, P, Eigen::VectorXd::Constant(1, 0.12),
 *     Eigen::VectorXd::Constant(1, 0.001));
 * @endcode
 */
[[nodiscard]] PortfolioWeights black_litterman(
    const Eigen::Ref<const Eigen::MatrixXd>& covariance,
    const Eigen::Ref<const Eigen::VectorXd>& market_weights,
    const Eigen::Ref<const Eigen::MatrixXd>& picking_matrix,
    const Eigen::Ref<const Eigen::VectorXd>& view_returns,
    const Eigen::Ref<const Eigen::VectorXd>& view_uncertainty, double risk_aversion = 2.5,
    double tau = 0.05, bool long_only = true);

}  // namespace zinc::opt
