/**
 * @file   opt_mvo_test.cpp
 * @brief  Unit tests for zinc::opt::mvo.
 */

#include "zinc/opt/mvo.hpp"

#include <cmath>
#include <vector>

#include <Eigen/Dense>

#include <gtest/gtest.h>
#include <random>

namespace {

bool WeightsValid(const std::vector<double>& weights) {
    if (weights.empty()) {
        return false;
    }
    double sum = 0.0;
    for (const double weight : weights) {
        if (weight < -1e-12) {
            return false;
        }
        sum += weight;
    }
    return std::abs(sum - 1.0) < 1e-8;
}

} // namespace

TEST(OptMvoTest, HappyPathMinimumVarianceHandComputed) {
    Eigen::Vector2d expected_returns = Eigen::Vector2d::Zero();
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;

    const auto result = zinc::opt::mvo(expected_returns, covariance, 1.0);
    ASSERT_EQ(result.weights.size(), 2U);
    EXPECT_NEAR(result.weights[0], 0.7272727272727273, 1e-6);
    EXPECT_NEAR(result.weights[1], 0.2727272727272727, 1e-6);
    EXPECT_TRUE(WeightsValid(result.weights));
}

TEST(OptMvoTest, EmptyAndInvalidInputReturnsEmpty) {
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;
    Eigen::Vector2d expected_returns(0.1, 0.05);

    EXPECT_TRUE(zinc::opt::mvo(Eigen::VectorXd{}, covariance).weights.empty());
    EXPECT_TRUE(zinc::opt::mvo(expected_returns, Eigen::MatrixXd{}).weights.empty());
    EXPECT_TRUE(zinc::opt::mvo(expected_returns, covariance, 0.0).weights.empty());
}

TEST(OptMvoTest, SingleAssetReturnsUnitWeight) {
    Eigen::VectorXd expected_returns(1);
    expected_returns << 0.08;
    Eigen::MatrixXd covariance(1, 1);
    covariance << 0.05;

    const auto result = zinc::opt::mvo(expected_returns, covariance);
    ASSERT_EQ(result.weights.size(), 1U);
    EXPECT_DOUBLE_EQ(result.weights[0], 1.0);
}

TEST(OptMvoTest, RandomCovarianceProducesValidLongOnlyWeights) {
    std::mt19937_64 rng(0x4D564F123ULL);
    std::normal_distribution<double> normal(0.0, 1.0);

    const int assets = 12;
    Eigen::MatrixXd factor(assets, assets);
    for (int row = 0; row < assets; ++row) {
        for (int column = 0; column < assets; ++column) {
            factor(row, column) = normal(rng);
        }
    }
    const Eigen::MatrixXd covariance =
        factor * factor.transpose() + Eigen::MatrixXd::Identity(assets, assets) * 1e-3;
    Eigen::VectorXd expected_returns(assets);
    for (int index = 0; index < assets; ++index) {
        expected_returns(index) = normal(rng) * 0.01;
    }

    const auto result = zinc::opt::mvo(expected_returns, covariance, 2.0);
    ASSERT_EQ(result.weights.size(), static_cast<std::size_t>(assets));
    EXPECT_TRUE(WeightsValid(result.weights));
}

TEST(OptMvoTest, NumericalStabilityScaleInvariantMinimumVariance) {
    Eigen::Vector2d expected_returns = Eigen::Vector2d::Zero();
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;

    const auto base = zinc::opt::mvo(expected_returns, covariance, 1.0);
    const auto scaled = zinc::opt::mvo(expected_returns, covariance * 1.0e6, 1.0);

    ASSERT_EQ(base.weights.size(), scaled.weights.size());
    EXPECT_NEAR(base.weights[0], scaled.weights[0], 1e-6);
    EXPECT_NEAR(base.weights[1], scaled.weights[1], 1e-6);
}
