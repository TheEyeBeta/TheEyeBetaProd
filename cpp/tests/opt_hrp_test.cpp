/**
 * @file   opt_hrp_test.cpp
 * @brief  Unit tests for zinc::opt::hrp.
 */

#include "zinc/opt/hrp.hpp"

#include <chrono>
#include <cmath>
#include <vector>

#include <Eigen/Dense>

#include <gtest/gtest.h>
#include <random>

namespace {

bool WeightsValid(const std::vector<double>& weights) {
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

TEST(OptHrpTest, HappyPathEqualVarianceDiagonalHandComputed) {
    // Two uncorrelated assets with equal variance → 50/50 recursive bisection split.
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.0, 0.0, 0.04;

    const auto result = zinc::opt::hrp(covariance);
    ASSERT_EQ(result.weights.size(), 2U);
    EXPECT_NEAR(result.weights[0], 0.5, 1e-6);
    EXPECT_NEAR(result.weights[1], 0.5, 1e-6);
    EXPECT_TRUE(WeightsValid(result.weights));
}

TEST(OptHrpTest, EmptyAndInvalidInputReturnsEmpty) {
    EXPECT_TRUE(zinc::opt::hrp(Eigen::MatrixXd{}).weights.empty());

    Eigen::MatrixXd rectangular(2, 1);
    rectangular << 0.04, 0.01;
    EXPECT_TRUE(zinc::opt::hrp(rectangular).weights.empty());
}

TEST(OptHrpTest, SingleAssetReturnsUnitWeight) {
    Eigen::MatrixXd covariance(1, 1);
    covariance << 0.05;

    const auto result = zinc::opt::hrp(covariance);
    ASSERT_EQ(result.weights.size(), 1U);
    EXPECT_DOUBLE_EQ(result.weights[0], 1.0);
}

TEST(OptHrpTest, RandomCovarianceProducesValidWeightsUnderOneHundredMilliseconds) {
    std::mt19937_64 rng(0x485250100ULL);
    std::normal_distribution<double> normal(0.0, 1.0);

    const int assets = 100;
    Eigen::MatrixXd factor(assets, assets);
    for (int row = 0; row < assets; ++row) {
        for (int column = 0; column < assets; ++column) {
            factor(row, column) = normal(rng) * 0.05;
        }
    }
    const Eigen::MatrixXd covariance =
        factor * factor.transpose() + Eigen::MatrixXd::Identity(assets, assets) * 1e-2;

    const auto start = std::chrono::steady_clock::now();
    const auto result = zinc::opt::hrp(covariance);
    const auto elapsed = std::chrono::steady_clock::now() - start;

    ASSERT_EQ(result.weights.size(), static_cast<std::size_t>(assets));
    EXPECT_TRUE(WeightsValid(result.weights));
    EXPECT_LT(std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count(), 100);
}

TEST(OptHrpTest, NumericalStabilityScaleInvariantWeights) {
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.0, 0.0, 0.04;

    const auto base = zinc::opt::hrp(covariance);
    const auto scaled = zinc::opt::hrp(covariance * 1.0e6);

    ASSERT_EQ(base.weights.size(), scaled.weights.size());
    EXPECT_NEAR(base.weights[0], scaled.weights[0], 1e-6);
    EXPECT_NEAR(base.weights[1], scaled.weights[1], 1e-6);
}
