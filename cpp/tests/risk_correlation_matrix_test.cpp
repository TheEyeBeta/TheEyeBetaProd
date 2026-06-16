/**
 * @file   risk_correlation_matrix_test.cpp
 * @brief  Unit tests for zinc::risk::correlation_matrix.
 */

#include "zinc/risk/correlation_matrix.hpp"

#include <cmath>
#include <limits>
#include <random>

#include <Eigen/Dense>
#include <gtest/gtest.h>

namespace {

bool IsNan(double value) {
    return std::isnan(value);
}

}  // namespace

TEST(CorrelationMatrixTest, HappyPathHandComputedPerfectCorrelation) {
    Eigen::MatrixXd data(3, 2);
    data << 1.0, 2.0, 2.0, 4.0, 3.0, 6.0;

    const Eigen::MatrixXd correlation = zinc::risk::correlation_matrix(data);
    EXPECT_NEAR(correlation(0, 0), 1.0, 1e-12);
    EXPECT_NEAR(correlation(1, 1), 1.0, 1e-12);
    EXPECT_NEAR(correlation(0, 1), 1.0, 1e-12);
    EXPECT_NEAR(correlation(1, 0), 1.0, 1e-12);
}

TEST(CorrelationMatrixTest, EmptyAndDegenerateInput) {
    const Eigen::MatrixXd empty(0, 2);
    const Eigen::MatrixXd empty_corr = zinc::risk::correlation_matrix(empty);
    EXPECT_EQ(empty_corr.rows(), 2);
    EXPECT_EQ(empty_corr.cols(), 2);
    EXPECT_TRUE(IsNan(empty_corr(0, 1)));

    const Eigen::MatrixXd single_row(1, 2);
    const Eigen::MatrixXd single_corr = zinc::risk::correlation_matrix(single_row);
    EXPECT_NEAR(single_corr(0, 0), 1.0, 1e-12);
    EXPECT_TRUE(IsNan(single_corr(0, 1)));
}

TEST(CorrelationMatrixTest, SingleColumnIdentity) {
    Eigen::MatrixXd data(4, 1);
    data << 1.0, 2.0, 3.0, 4.0;

    const Eigen::MatrixXd correlation = zinc::risk::correlation_matrix(data);
    ASSERT_EQ(correlation.rows(), 1);
    ASSERT_EQ(correlation.cols(), 1);
    EXPECT_NEAR(correlation(0, 0), 1.0, 1e-12);
}

TEST(CorrelationMatrixTest, RandomMatrixIsSymmetricWithUnitDiagonal) {
    std::mt19937_64 rng(0x5151U);
    std::normal_distribution<double> normal(0.0, 1.0);

    Eigen::MatrixXd data(200, 4);
    for (Eigen::Index row = 0; row < data.rows(); ++row) {
        for (Eigen::Index column = 0; column < data.cols(); ++column) {
            data(row, column) = normal(rng);
        }
    }

    const Eigen::MatrixXd correlation = zinc::risk::correlation_matrix(data);
    EXPECT_NEAR((correlation - correlation.transpose()).norm(), 0.0, 1e-12);
    for (Eigen::Index index = 0; index < correlation.rows(); ++index) {
        EXPECT_NEAR(correlation(index, index), 1.0, 1e-12);
        EXPECT_GE(correlation(index, (index + 1) % correlation.cols()), -1.0 - 1e-12);
        EXPECT_LE(correlation(index, (index + 1) % correlation.cols()), 1.0 + 1e-12);
    }
}

TEST(CorrelationMatrixTest, NumericalStabilityAgainstReferenceLiteral) {
    Eigen::MatrixXd data(4, 2);
    data << 10.0, 40.0, 20.0, 30.0, 30.0, 20.0, 40.0, 10.0;

    constexpr double kReferenceCorrelation = -0.9;
    const Eigen::MatrixXd correlation = zinc::risk::correlation_matrix(data);
    EXPECT_NEAR(correlation(0, 1), kReferenceCorrelation, 1e-12);
    EXPECT_NEAR(correlation(1, 0), kReferenceCorrelation, 1e-12);
}
