/**
 * @file   risk_max_drawdown_test.cpp
 * @brief  Unit tests for zinc::risk::max_drawdown.
 */

#include "zinc/risk/max_drawdown.hpp"

#include <cmath>
#include <limits>
#include <span>
#include <vector>

#include <gtest/gtest.h>
#include <random>

namespace {

bool IsNan(double value) {
    return std::isnan(value);
}

} // namespace

TEST(MaxDrawdownTest, HappyPathHandComputed) {
    const double wealth[] = {100.0, 120.0, 90.0, 110.0};
    const double drawdown = zinc::risk::max_drawdown(wealth);
    EXPECT_NEAR(drawdown, 0.25, 1e-12);
}

TEST(MaxDrawdownTest, EmptyAndInvalidInputReturnsNan) {
    EXPECT_TRUE(IsNan(zinc::risk::max_drawdown(std::span<const double>{})));
    const double non_positive[] = {100.0, 0.0, 50.0};
    EXPECT_TRUE(IsNan(zinc::risk::max_drawdown(non_positive)));
}

TEST(MaxDrawdownTest, SingleElementReturnsZero) {
    const double wealth = 50.0;
    EXPECT_DOUBLE_EQ(zinc::risk::max_drawdown(std::span<const double>(&wealth, 1)), 0.0);
}

TEST(MaxDrawdownTest, RandomWalkDrawdownBounded) {
    std::mt19937_64 rng(0xA11CEU);
    std::lognormal_distribution<double> log_normal(0.0, 0.05);

    std::vector<double> wealth(500);
    wealth.front() = 100.0;
    for (std::size_t index = 1; index < wealth.size(); ++index) {
        wealth[index] = wealth[index - 1] * log_normal(rng);
    }

    const double drawdown = zinc::risk::max_drawdown(wealth);
    EXPECT_GE(drawdown, 0.0);
    EXPECT_LE(drawdown, 1.0);
}

TEST(MaxDrawdownTest, NumericalStabilityAgainstReferenceLiteral) {
    const double wealth[] = {1.0e6, 1.2e6, 9.0e5, 1.1e6};
    constexpr double kReferenceDrawdown = 0.25;
    const double drawdown = zinc::risk::max_drawdown(wealth);
    EXPECT_NEAR(drawdown, kReferenceDrawdown, 1e-12);
}
