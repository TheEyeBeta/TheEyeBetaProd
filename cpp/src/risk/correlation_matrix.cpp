/**
 * @file   correlation_matrix.cpp
 * @brief  Pearson correlation matrix implementation.
 */

#include "zinc/risk/correlation_matrix.hpp"

#include <cmath>
#include <limits>

namespace zinc::risk {

namespace {

constexpr double kZeroVarianceEpsilon = 1e-15;

}  // namespace

Eigen::MatrixXd correlation_matrix(const Eigen::Ref<const Eigen::MatrixXd>& data) {
    const Eigen::Index observations = data.rows();
    const Eigen::Index variables = data.cols();

    Eigen::MatrixXd correlation =
        Eigen::MatrixXd::Constant(variables, variables, std::numeric_limits<double>::quiet_NaN());

    if (variables == 0) {
        return correlation;
    }

    correlation.setIdentity();

    if (observations < 2) {
        for (Eigen::Index row = 0; row < variables; ++row) {
            for (Eigen::Index column = 0; column < variables; ++column) {
                if (row != column) {
                    correlation(row, column) = std::numeric_limits<double>::quiet_NaN();
                }
            }
        }
        return correlation;
    }

    const Eigen::VectorXd means = data.colwise().mean();
    const Eigen::MatrixXd centered = data.rowwise() - means.transpose();
    const double sample_count = static_cast<double>(observations - 1);

    Eigen::VectorXd stddev(variables);
    for (Eigen::Index column = 0; column < variables; ++column) {
        const double variance = centered.col(column).squaredNorm() / sample_count;
        stddev(column) = std::sqrt(variance);
    }

    for (Eigen::Index row = 0; row < variables; ++row) {
        for (Eigen::Index column = row; column < variables; ++column) {
            if (row == column) {
                correlation(row, column) =
                    stddev(row) > kZeroVarianceEpsilon ? 1.0 : std::numeric_limits<double>::quiet_NaN();
                continue;
            }

            if (stddev(row) <= kZeroVarianceEpsilon || stddev(column) <= kZeroVarianceEpsilon) {
                correlation(row, column) = std::numeric_limits<double>::quiet_NaN();
                correlation(column, row) = std::numeric_limits<double>::quiet_NaN();
                continue;
            }

            const double covariance = centered.col(row).dot(centered.col(column)) / sample_count;
            const double value = covariance / (stddev(row) * stddev(column));
            correlation(row, column) = value;
            correlation(column, row) = value;
        }
    }

    return correlation;
}

}  // namespace zinc::risk
