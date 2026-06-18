/**
 * @file   ta_bollinger_test.cpp
 * @brief  Unit tests for zinc::ta::bollinger.
 */

#include "ta_test_reference.hpp"
#include "zinc/ta/bollinger.hpp"

#include <cmath>
#include <vector>

#include <gtest/gtest.h>
#include <random>

namespace {

constexpr int kPeriod = 3;

} // namespace

TEST(TaBollingerTest, HappyPathPandasTaReferenceLiteral) {
    const auto closes = zinc::ta_test::reference_closes();
    const auto bands = zinc::ta::bollinger(closes, kPeriod, 2.0);
    ASSERT_EQ(bands.middle.size(), closes.size());
    EXPECT_NEAR(bands.middle[2], 10.0, 1e-12);
    EXPECT_NEAR(bands.middle[9], 15.0, 1e-12);
    EXPECT_NEAR(bands.upper[2], 11.632993161855648, 1e-8);
    EXPECT_NEAR(bands.lower[2], 8.367006838144352, 1e-8);
    EXPECT_NEAR(bands.upper[9], 16.632993161855648, 1e-8);
    EXPECT_NEAR(bands.lower[9], 13.367006838144352, 1e-8);
}

TEST(TaBollingerTest, EmptyAndInvalidPeriodReturnsEmptyBands) {
    const auto closes = zinc::ta_test::reference_closes();
    EXPECT_TRUE(zinc::ta::bollinger({}, kPeriod).middle.empty());
    EXPECT_TRUE(zinc::ta::bollinger(closes, 0).middle.empty());
    EXPECT_TRUE(zinc::ta::bollinger(closes, kPeriod, 0.0).middle.empty());
}

TEST(TaBollingerTest, SingleElementPeriodOneEqualsClose) {
    const std::vector<double> series{7.5};
    const auto bands = zinc::ta::bollinger(series, 1, 2.0);
    ASSERT_EQ(bands.middle.size(), 1U);
    EXPECT_NEAR(bands.middle[0], 7.5, 1e-12);
    EXPECT_NEAR(bands.upper[0], 7.5, 1e-12);
    EXPECT_NEAR(bands.lower[0], 7.5, 1e-12);
}

TEST(TaBollingerTest, RandomSeriesUpperDominatesLower) {
    std::mt19937_64 rng(0xBB01ULL);
    std::normal_distribution<double> normal(50.0, 5.0);
    std::vector<double> series(80);
    for (double& value : series) {
        value = normal(rng);
    }

    const auto bands = zinc::ta::bollinger(series, 20, 2.0);
    for (std::size_t index = 19; index < series.size(); ++index) {
        EXPECT_GE(bands.upper[index], bands.middle[index]);
        EXPECT_LE(bands.lower[index], bands.middle[index]);
    }
}

TEST(TaBollingerTest, NumericalStabilityLargeMagnitude) {
    const std::vector<double> series{1.0e6, 1.2e6, 0.9e6, 1.1e6};
    const auto bands = zinc::ta::bollinger(series, 3, 2.0);
    EXPECT_NEAR(bands.middle[3], 1066666.6666666667, 1.0);
    EXPECT_NEAR(bands.upper[3] - bands.middle[3], bands.middle[3] - bands.lower[3], 1.0);
}
