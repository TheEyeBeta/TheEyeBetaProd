/**
 * @file   correlation_matrix.hpp
 * @brief  Pearson correlation matrix for multivariate samples.
 */

#pragma once

#include <Eigen/Dense>

namespace zinc::risk {

/**
 * @brief Pearson correlation matrix of column variables.
 *
 * Each row of @p data is one observation; each column is one variable.
 * Uses sample covariance with Bessel correction (@f$n-1@f$ denominator).
 * Diagonal entries are @c 1.0 when the column standard deviation is positive;
 * off-diagonal entries are quiet_NaN when either column has zero variance.
 *
 * @param data @f$n \times p@f$ matrix (@f$n \ge 2@f$ observations, @f$p \ge 1@f$ variables).
 *
 * @return @f$p \times p@f$ symmetric correlation matrix.
 *
 * @pre @p data.rows() &ge; 2 and @p data.cols() &ge; 1 for defined off-diagonal entries.
 *
 * @example
 * @code
 * Eigen::MatrixXd x(3, 2);
 * x << 1.0, 2.0,
 *      2.0, 4.0,
 *      3.0, 6.0;
 * const Eigen::MatrixXd corr = zinc::risk::correlation_matrix(x);
 * // corr(0, 1) == 1.0 (perfect linear dependence)
 * @endcode
 */
[[nodiscard]] Eigen::MatrixXd correlation_matrix(const Eigen::Ref<const Eigen::MatrixXd>& data);

}  // namespace zinc::risk
