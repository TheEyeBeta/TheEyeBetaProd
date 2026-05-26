/**
 * @file   risk_historical_var_test.cpp
 * @brief  Unit tests for zinc::risk::historical_var.
 */

#include "zinc/risk/historical_var.hpp"

#include <cmath>
#include <limits>
#include <random>
#include <span>
#include <vector>

#include <gtest/gtest.h>

namespace {

constexpr double kPhiInv005 = -1.6448536269514102;

bool IsNan(double value) {
    return std::isnan(value);
}

}  // namespace

TEST(HistoricalVarTest, HappyPathHandComputed) {
    const double samples[] = {-5.0, -3.0, -2.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0};
    const double var = zinc::risk::historical_var(samples, 0.20);
    EXPECT_DOUBLE_EQ(var, -3.0);
}

TEST(HistoricalVarTest, EmptyInputReturnsNan) {
    const double alpha = 0.05;
    EXPECT_TRUE(IsNan(zinc::risk::historical_var(std::span<const double>{}, alpha)));
    EXPECT_TRUE(IsNan(zinc::risk::historical_var(std::span<const double>{}, 0.0)));
    EXPECT_TRUE(IsNan(zinc::risk::historical_var(std::span<const double>{}, 1.0)));
}

TEST(HistoricalVarTest, SingleElementReturnsThatValue) {
    const double sample = 0.42;
    EXPECT_DOUBLE_EQ(zinc::risk::historical_var(std::span<const double>(&sample, 1), 0.05), sample);
}

TEST(HistoricalVarTest, NormalTailMatchesInversePhiWithinTwoPercent) {
    std::mt19937_64 rng(0xC0FFEE42U);
    std::normal_distribution<double> normal(0.0, 1.0);

    std::vector<double> samples;
    samples.reserve(50'000);
    for (int index = 0; index < 50'000; ++index) {
        samples.push_back(normal(rng));
    }

    const double var = zinc::risk::historical_var(samples, 0.05);
    const double relative_error = std::abs((var - kPhiInv005) / kPhiInv005);
    EXPECT_LT(relative_error, 0.02);
}

TEST(HistoricalVarTest, NumericalStabilityAgainstReferenceLiteral) {
    // Reference: sorted ascending; alpha=0.25, n=8 => rank ceil(2)=2 => -2.0
    const double samples[] = {3.0, -1.0, 2.0, -2.0, 0.0, 1.0, -3.0, 4.0};
    constexpr double kReferenceVar = -2.0;
    const double var = zinc::risk::historical_var(samples, 0.25);
    EXPECT_DOUBLE_EQ(var, kReferenceVar);
}
