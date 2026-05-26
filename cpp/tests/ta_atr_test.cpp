/**
 * @file   ta_atr_test.cpp
 * @brief  Unit tests for zinc::ta::atr.
 */

#include "zinc/ta/atr.hpp"

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

TEST(TaAtrTest, HappyPathPandasTaReferenceLiteral) {
    const auto bars = zinc::ta_test::reference_bars();
    const auto values = zinc::ta::atr(bars, kPeriod);
    ASSERT_EQ(values.size(), bars.size());
    EXPECT_NEAR(values[2], 2.333333333333333, 1e-8);
    EXPECT_NEAR(values[5], 2.802469135802469, 1e-8);
    EXPECT_NEAR(values[9], 2.960981562660121, 1e-8);
}

TEST(TaAtrTest, EmptyAndInvalidPeriodReturnsEmpty) {
    const auto bars = zinc::ta_test::reference_bars();
    EXPECT_TRUE(zinc::ta::atr({}, kPeriod).empty());
    EXPECT_TRUE(zinc::ta::atr(bars, 0).empty());
}

TEST(TaAtrTest, SingleBarPeriodOneEqualsTrueRange) {
    const std::vector<zinc::ta::Bar> bars{{1.0, 5.0, 0.5, 3.0}};
    const auto values = zinc::ta::atr(bars, 1);
    ASSERT_EQ(values.size(), 1U);
    EXPECT_NEAR(values[0], 4.5, 1e-12);
}

TEST(TaAtrTest, RandomBarsProducePositiveFiniteAtr) {
    std::mt19937_64 rng(0xA7C42ULL);
    std::uniform_real_distribution<double> price(10.0, 100.0);

    std::vector<zinc::ta::Bar> bars(100);
    double last_close = price(rng);
    for (auto& bar : bars) {
        const double close = price(rng);
        bar.high = std::max(close, last_close) + 1.0;
        bar.low = std::min(close, last_close) - 1.0;
        bar.open = last_close;
        bar.close = close;
        last_close = close;
    }

    const auto values = zinc::ta::atr(bars, 14);
    for (std::size_t index = 13; index < values.size(); ++index) {
        EXPECT_TRUE(std::isfinite(values[index]));
        EXPECT_GT(values[index], 0.0);
    }
}

TEST(TaAtrTest, NumericalStabilityLargePrices) {
    const std::vector<zinc::ta::Bar> bars{
        {1.0e6, 1.01e6, 0.99e6, 1.0e6},
        {1.0e6, 1.02e6, 0.98e6, 1.01e6},
        {1.01e6, 1.03e6, 1.0e6, 1.02e6},
    };
    const auto values = zinc::ta::atr(bars, 3);
    EXPECT_NEAR(values[2], 30000.0, 1e-3);
}
