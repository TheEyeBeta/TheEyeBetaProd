/**
 * @file   ta_zscore_test.cpp
 * @brief  Unit tests for zinc::ta::zscore.
 */

#include "zinc/ta/zscore.hpp"

#include <cmath>
#include <random>
#include <vector>

#include <gtest/gtest.h>

#include "ta_test_reference.hpp"

namespace {

bool IsNan(double value) {
    return std::isnan(value);
}

constexpr int kPeriod = 3;

}  // namespace

TEST(TaZscoreTest, HappyPathPandasTaReferenceLiteral) {
    const auto closes = zinc::ta_test::reference_closes();
    const auto values = zinc::ta::zscore(closes, kPeriod);
    ASSERT_EQ(values.size(), closes.size());
    EXPECT_TRUE(IsNan(values[0]));
    EXPECT_TRUE(IsNan(values[1]));
    EXPECT_NEAR(values[2], 0.0, 1e-12);
    EXPECT_NEAR(values[3], 1.224744871391589, 1e-8);
    EXPECT_NEAR(values[9], 1.224744871391589, 1e-8);
}

TEST(TaZscoreTest, EmptyAndInvalidPeriodReturnsEmpty) {
    const auto closes = zinc::ta_test::reference_closes();
    EXPECT_TRUE(zinc::ta::zscore({}, kPeriod).empty());
    EXPECT_TRUE(zinc::ta::zscore(closes, 0).empty());
}

TEST(TaZscoreTest, SingleElementReturnsNan) {
    const std::vector<double> series{42.0};
    const auto values = zinc::ta::zscore(series, 3);
    ASSERT_EQ(values.size(), 1U);
    EXPECT_TRUE(IsNan(values[0]));
}

TEST(TaZscoreTest, ConstantWindowYieldsZero) {
    const std::vector<double> series{5.0, 5.0, 5.0, 5.0};
    const auto values = zinc::ta::zscore(series, 3);
    EXPECT_NEAR(values[2], 0.0, 1e-12);
    EXPECT_NEAR(values[3], 0.0, 1e-12);
}

TEST(TaZscoreTest, NumericalStabilityLargeMagnitude) {
    const std::vector<double> series{1.0e9, 1.0e9 + 2.0, 1.0e9 + 4.0, 1.0e9 + 6.0};
    const auto values = zinc::ta::zscore(series, 3);
    EXPECT_NEAR(values[3], 1.224744871391589, 1e-6);
}
