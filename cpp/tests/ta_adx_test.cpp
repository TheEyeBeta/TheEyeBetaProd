/**
 * @file   ta_adx_test.cpp
 * @brief  Unit tests for zinc::ta::adx.
 */

#include "zinc/ta/adx.hpp"

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

TEST(TaAdxTest, HappyPathPandasTaReferenceLiteral) {
    const auto bars = zinc::ta_test::reference_bars();
    const auto values = zinc::ta::adx(bars, kPeriod);
    ASSERT_EQ(values.size(), bars.size());
    EXPECT_NEAR(values[2], 33.333333333333336, 1e-8);
    EXPECT_NEAR(values[5], 59.070442988005545, 1e-8);
    EXPECT_NEAR(values[9], 55.33901818766078, 1e-8);
}

TEST(TaAdxTest, EmptyAndInvalidPeriodReturnsEmpty) {
    const auto bars = zinc::ta_test::reference_bars();
    EXPECT_TRUE(zinc::ta::adx({}, kPeriod).empty());
    EXPECT_TRUE(zinc::ta::adx(bars, 0).empty());
}

TEST(TaAdxTest, SingleBarReturnsNan) {
    const std::vector<zinc::ta::Bar> bars{{1.0, 2.0, 0.5, 1.5}};
    const auto values = zinc::ta::adx(bars, 3);
    ASSERT_EQ(values.size(), 1U);
    EXPECT_TRUE(IsNan(values[0]));
}

TEST(TaAdxTest, RandomBarsAdxBoundedZeroToOneHundred) {
    std::mt19937_64 rng(0xADX123ULL);
    std::uniform_real_distribution<double> price(20.0, 80.0);

    std::vector<zinc::ta::Bar> bars(120);
    double last_close = price(rng);
    for (auto& bar : bars) {
        const double close = price(rng);
        bar.high = std::max(close, last_close) + 0.5;
        bar.low = std::min(close, last_close) - 0.5;
        bar.open = last_close;
        bar.close = close;
        last_close = close;
    }

    const auto values = zinc::ta::adx(bars, 14);
    for (std::size_t index = 27; index < values.size(); ++index) {
        if (std::isfinite(values[index])) {
            EXPECT_GE(values[index], 0.0);
            EXPECT_LE(values[index], 100.0);
        }
    }
}

TEST(TaAdxTest, NumericalStabilityLargePrices) {
    const auto bars = zinc::ta_test::reference_bars();
    std::vector<zinc::ta::Bar> scaled = bars;
    for (auto& bar : scaled) {
        bar.open *= 1.0e6;
        bar.high *= 1.0e6;
        bar.low *= 1.0e6;
        bar.close *= 1.0e6;
    }
    const auto reference = zinc::ta::adx(bars, kPeriod);
    const auto scaled_values = zinc::ta::adx(scaled, kPeriod);
    ASSERT_EQ(reference.size(), scaled_values.size());
    for (std::size_t index = 2; index < reference.size(); ++index) {
        if (std::isfinite(reference[index])) {
            EXPECT_NEAR(reference[index], scaled_values[index], 1e-6);
        }
    }
}
