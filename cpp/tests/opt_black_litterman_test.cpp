/**
 * @file   opt_black_litterman_test.cpp
 * @brief  Unit tests for zinc::opt::black_litterman.
 */

#include "zinc/opt/black_litterman.hpp"

#include <cmath>
#include <random>
#include <vector>

#include <Eigen/Dense>
#include <gtest/gtest.h>

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

}  // namespace

TEST(OptBlackLittermanTest, HappyPathHandComputedPosteriorWeights) {
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;
    Eigen::Vector2d market_weights(0.6, 0.4);
    Eigen::MatrixXd picking_matrix(1, 2);
    picking_matrix << 1.0, 0.0;
    Eigen::VectorXd view_returns(1);
    view_returns << 0.12;
    Eigen::VectorXd view_uncertainty(1);
    view_uncertainty << 0.001;

    const auto result =
        zinc::opt::black_litterman(covariance, market_weights, picking_matrix, view_returns,
                                   view_uncertainty, 2.5, 0.05);
    ASSERT_EQ(result.weights.size(), 2U);
    EXPECT_NEAR(result.weights[0], 0.69090909, 1e-5);
    EXPECT_NEAR(result.weights[1], 0.30909091, 1e-5);
    EXPECT_TRUE(WeightsValid(result.weights));
}

TEST(OptBlackLittermanTest, EmptyAndInvalidInputReturnsEmpty) {
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;
    Eigen::Vector2d market_weights(0.5, 0.5);
    Eigen::MatrixXd picking_matrix = Eigen::MatrixXd::Identity(2, 2);
    Eigen::Vector2d view_returns(0.1, 0.05);
    Eigen::Vector2d view_uncertainty(0.001, 0.001);

    EXPECT_TRUE(zinc::opt::black_litterman(Eigen::MatrixXd{}, market_weights, picking_matrix,
                                           view_returns, view_uncertainty)
                    .weights.empty());
    EXPECT_TRUE(zinc::opt::black_litterman(covariance, Eigen::VectorXd{}, picking_matrix,
                                           view_returns, view_uncertainty)
                    .weights.empty());

    Eigen::Vector2d bad_uncertainty(0.0, 0.001);
    EXPECT_TRUE(zinc::opt::black_litterman(covariance, market_weights, picking_matrix,
                                           view_returns, bad_uncertainty)
                    .weights.empty());
}

TEST(OptBlackLittermanTest, SingleAssetReturnsUnitWeight) {
    Eigen::MatrixXd covariance(1, 1);
    covariance << 0.02;
    Eigen::VectorXd market_weights(1);
    market_weights << 1.0;
    Eigen::MatrixXd picking_matrix(1, 1);
    picking_matrix << 1.0;
    Eigen::VectorXd view_returns(1);
    view_returns << 0.08;
    Eigen::VectorXd view_uncertainty(1);
    view_uncertainty << 0.001;

    const auto result = zinc::opt::black_litterman(covariance, market_weights, picking_matrix,
                                                   view_returns, view_uncertainty);
    ASSERT_EQ(result.weights.size(), 1U);
    EXPECT_DOUBLE_EQ(result.weights[0], 1.0);
}

TEST(OptBlackLittermanTest, RandomViewsProduceValidWeights) {
    std::mt19937_64 rng(0x0B142ULL);
    std::normal_distribution<double> normal(0.0, 1.0);

    const int assets = 8;
    Eigen::MatrixXd factor(assets, assets);
    for (int row = 0; row < assets; ++row) {
        for (int column = 0; column < assets; ++column) {
            factor(row, column) = normal(rng) * 0.1;
        }
    }
    const Eigen::MatrixXd covariance =
        factor * factor.transpose() + Eigen::MatrixXd::Identity(assets, assets) * 1e-2;

    Eigen::VectorXd market_weights(assets);
    market_weights.setConstant(1.0 / static_cast<double>(assets));

    Eigen::MatrixXd picking_matrix = Eigen::MatrixXd::Identity(assets, assets);
    Eigen::VectorXd view_returns(assets);
    Eigen::VectorXd view_uncertainty(assets);
    for (int index = 0; index < assets; ++index) {
        view_returns(index) = 0.05 + 0.01 * normal(rng);
        view_uncertainty(index) = 0.001 + std::abs(normal(rng)) * 0.0005;
    }

    const auto result = zinc::opt::black_litterman(covariance, market_weights, picking_matrix,
                                                   view_returns, view_uncertainty);
    ASSERT_EQ(result.weights.size(), static_cast<std::size_t>(assets));
    EXPECT_TRUE(WeightsValid(result.weights));
}

TEST(OptBlackLittermanTest, NumericalStabilityScaledCovariance) {
    Eigen::Matrix2d covariance;
    covariance << 0.04, 0.01, 0.01, 0.09;
    Eigen::Vector2d market_weights(0.6, 0.4);
    Eigen::MatrixXd picking_matrix(1, 2);
    picking_matrix << 1.0, 0.0;
    Eigen::VectorXd view_returns(1);
    view_returns << 0.12;
    Eigen::VectorXd view_uncertainty(1);
    view_uncertainty << 0.001;

    const auto base = zinc::opt::black_litterman(covariance, market_weights, picking_matrix,
                                                 view_returns, view_uncertainty);
    const auto scaled = zinc::opt::black_litterman(
        covariance * 1.0e6, market_weights, picking_matrix, view_returns, view_uncertainty);

    ASSERT_EQ(base.weights.size(), scaled.weights.size());
    EXPECT_NEAR(base.weights[0], scaled.weights[0], 1e-5);
    EXPECT_NEAR(base.weights[1], scaled.weights[1], 1e-5);
}
