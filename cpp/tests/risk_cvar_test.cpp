/**
 * @file   risk_cvar_test.cpp
 * @brief  Unit tests for zinc::risk::cvar.
 */

#include "zinc/risk/cvar.hpp"
#include "zinc/risk/historical_var.hpp"

#include <cmath>
#include <limits>
#include <random>
#include <span>
#include <vector>

#include <gtest/gtest.h>

namespace {

bool IsNan(double value) {
    return std::isnan(value);
}

}  // namespace

TEST(CvarTest, HappyPathHandComputed) {
    const double samples[] = {-5.0, -3.0, -2.0, 0.0, 1.0};
    const double expected = (-5.0 + -3.0) / 2.0;
    const double es = zinc::risk::cvar(samples, 0.40);
    EXPECT_NEAR(es, expected, 1e-12);
}

TEST(CvarTest, EmptyInputReturnsNan) {
    EXPECT_TRUE(IsNan(zinc::risk::cvar(std::span<const double>{}, 0.05)));
    EXPECT_TRUE(IsNan(zinc::risk::cvar(std::span<const double>{}, -0.1)));
    EXPECT_TRUE(IsNan(zinc::risk::cvar(std::span<const double>{}, 1.0)));
}

TEST(CvarTest, SingleElementReturnsThatValue) {
    const double sample = -1.25;
    EXPECT_DOUBLE_EQ(zinc::risk::cvar(std::span<const double>(&sample, 1), 0.10), sample);
}

TEST(CvarTest, TailMeanNotAboveVarForRandomData) {
    std::mt19937_64 rng(0xDEADBEEFU);
    std::uniform_real_distribution<double> uniform(-2.0, 2.0);

    std::vector<double> samples(2'000);
    for (double& value : samples) {
        value = uniform(rng);
    }

    const double alpha = 0.10;
    const double var = zinc::risk::historical_var(samples, alpha);
    const double es = zinc::risk::cvar(samples, alpha);
    EXPECT_LE(es, var + 1e-12);
}

TEST(CvarTest, NumericalStabilityAgainstReferenceLiteral) {
    const double samples[] = {-5.0, -3.0, -2.0, 0.0, 1.0, 2.0};
    constexpr double kReferenceCvar = -3.3333333333333335;
    const double es = zinc::risk::cvar(samples, 0.50);
    EXPECT_NEAR(es, kReferenceCvar, 1e-12);
}
