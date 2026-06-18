/**
 * @file   bt_engine_test.cpp
 * @brief  Unit tests for zinc::bt::Engine.
 */

#include "bt_test_parquet.hpp"
#include "zinc/bt/engine.hpp"
#include "zinc/bt/slippage_model.hpp"

#include <cmath>
#include <filesystem>
#include <numeric>
#include <string>
#include <vector>

#include <cstdio>
#include <gtest/gtest.h>
#include <random>

namespace {

constexpr double kGrowthPerDay = 1.0001;
constexpr int kBuyHoldDays = 100;
constexpr double kReferenceTotalReturn = 0.009950330903168; // 1.0001^99 - 1

zinc::bt::SlippageModel ZeroSlippage() {
    return zinc::bt::SlippageModel([](const double, const double) { return 0.0; });
}

std::filesystem::path write_buy_hold_fixture() {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() / "zinc_bt_engine_test";
    std::filesystem::create_directories(directory);
    const std::filesystem::path parquet_path = directory / "daily.parquet";

    std::vector<zinc::bt::test::DailyMarketRow> rows;
    rows.reserve(static_cast<std::size_t>(kBuyHoldDays));

    for (int day = 0; day < kBuyHoldDays; ++day) {
        const int month = 1 + day / 31;
        const int day_of_month = 1 + day % 31;
        char date_buffer[11];
        std::snprintf(date_buffer, sizeof(date_buffer), "2024-%02d-%02d", month, day_of_month);

        zinc::bt::test::DailyMarketRow row;
        row.trade_date = date_buffer;
        row.symbol = "SPY";
        row.close = 100.0 * std::pow(kGrowthPerDay, static_cast<double>(day));
        row.open = row.close;
        row.high = row.close;
        row.low = row.close;
        row.volume = 1'000'000;
        row.atr14 = 1.0;
        row.adv = 1.0e9;
        rows.push_back(std::move(row));
    }

    EXPECT_TRUE(zinc::bt::test::write_daily_parquet(parquet_path, rows));
    return parquet_path;
}

double sum_pnl(const std::vector<double>& daily_pnl) {
    return std::accumulate(daily_pnl.begin(), daily_pnl.end(), 0.0);
}

} // namespace

TEST(BtEngineTest, HappyPathBuyAndHoldWithinOneBasisPoint) {
    const std::filesystem::path parquet_path = write_buy_hold_fixture();

    zinc::bt::Engine engine("buy_hold", "2024-01-01", "2024-12-31", {"SPY"}, ZeroSlippage());
    engine.set_parquet_path(parquet_path);
    engine.set_strategy([](const zinc::bt::Snapshot&) {
        return zinc::bt::Decision{.symbol_index = 0, .target_weight = 1.0};
    });

    const zinc::bt::Result result = engine.run();
    ASSERT_EQ(result.daily_pnl.size(), static_cast<std::size_t>(kBuyHoldDays));
    ASSERT_EQ(result.drawdown_series.size(), static_cast<std::size_t>(kBuyHoldDays));
    EXPECT_EQ(result.executions.size(), 1U);

    const double total_from_pnl = sum_pnl(result.daily_pnl);
    EXPECT_NEAR(result.metrics.total_return, kReferenceTotalReturn, 1e-4);
    EXPECT_NEAR(total_from_pnl, kReferenceTotalReturn, 1e-4);
    EXPECT_NEAR(result.metrics.total_return, total_from_pnl, 1e-10);
    EXPECT_NEAR(result.metrics.max_drawdown, 0.0, 1e-12);
}

TEST(BtEngineTest, EmptyAndInvalidInputReturnsEmpty) {
    zinc::bt::Engine engine("noop", "2024-06-01", "2024-01-01", {"SPY"}, ZeroSlippage());
    engine.set_strategy([](const zinc::bt::Snapshot&) { return zinc::bt::Decision{}; });
    const zinc::bt::Result invalid_window = engine.run();
    EXPECT_TRUE(invalid_window.daily_pnl.empty());

    zinc::bt::Engine missing_data("noop", "2024-01-01", "2024-12-31", {}, ZeroSlippage());
    missing_data.set_strategy([](const zinc::bt::Snapshot&) { return zinc::bt::Decision{}; });
    const zinc::bt::Result empty_universe = missing_data.run();
    EXPECT_TRUE(empty_universe.daily_pnl.empty());
}

TEST(BtEngineTest, SingleTradingDayFlatPnl) {
    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() / "zinc_bt_engine_single";
    std::filesystem::create_directories(directory);
    const std::filesystem::path parquet_path = directory / "daily.parquet";

    const std::vector<zinc::bt::test::DailyMarketRow> rows = {
        {"2024-01-01", "SPY", 50.0, 50.0, 50.0, 50.0, 1000, 1.0, 1.0e9},
    };
    ASSERT_TRUE(zinc::bt::test::write_daily_parquet(parquet_path, rows));

    zinc::bt::Engine engine("single", "2024-01-01", "2024-01-01", {"SPY"}, ZeroSlippage());
    engine.set_parquet_path(parquet_path);
    engine.set_strategy([](const zinc::bt::Snapshot&) {
        return zinc::bt::Decision{.symbol_index = 0, .target_weight = 1.0};
    });

    const zinc::bt::Result result = engine.run();
    ASSERT_EQ(result.daily_pnl.size(), 1U);
    EXPECT_NEAR(result.daily_pnl.front(), 0.0, 1e-12);
    EXPECT_NEAR(result.metrics.total_return, 0.0, 1e-12);
}

TEST(BtEngineTest, RandomPricesProduceFiniteMetrics) {
    std::mt19937_64 rng(0x0B7123ULL);
    std::lognormal_distribution<double> log_normal(0.0, 0.01);

    const std::filesystem::path directory =
        std::filesystem::temp_directory_path() / "zinc_bt_engine_random";
    std::filesystem::create_directories(directory);
    const std::filesystem::path parquet_path = directory / "daily.parquet";

    std::vector<zinc::bt::test::DailyMarketRow> rows;
    double close = 100.0;
    for (int day = 0; day < 60; ++day) {
        close *= log_normal(rng);
        char date_buffer[11];
        std::snprintf(date_buffer, sizeof(date_buffer), "2024-01-%02d", day + 1);
        rows.push_back({date_buffer, "SPY", close, close, close, close, 1'000'000, 1.0, 1.0e9});
    }
    ASSERT_TRUE(zinc::bt::test::write_daily_parquet(parquet_path, rows));

    zinc::bt::Engine engine("random", "2024-01-01", "2024-03-31", {"SPY"}, ZeroSlippage());
    engine.set_parquet_path(parquet_path);
    engine.set_strategy([](const zinc::bt::Snapshot& snapshot) {
        const double weight = snapshot.day_index % 5 == 0 ? 1.0 : 1.0;
        return zinc::bt::Decision{.symbol_index = 0, .target_weight = weight};
    });

    const zinc::bt::Result result = engine.run();
    ASSERT_EQ(result.daily_pnl.size(), rows.size());
    for (const double pnl : result.daily_pnl) {
        EXPECT_TRUE(std::isfinite(pnl));
    }
    EXPECT_TRUE(std::isfinite(result.metrics.total_return));
    EXPECT_GE(result.metrics.max_drawdown, 0.0);
}

TEST(BtEngineTest, NumericalStabilityAgainstReferenceLiteral) {
    const double literal_total_return = kReferenceTotalReturn;
    const std::filesystem::path parquet_path = write_buy_hold_fixture();

    zinc::bt::Engine engine("literal", "2024-01-01", "2024-12-31", {"SPY"}, ZeroSlippage());
    engine.set_parquet_path(parquet_path);
    engine.set_strategy([](const zinc::bt::Snapshot&) {
        return zinc::bt::Decision{.symbol_index = 0, .target_weight = 1.0};
    });

    const zinc::bt::Result result = engine.run();
    EXPECT_NEAR(result.metrics.total_return, literal_total_return, 1e-4);
    EXPECT_NEAR(sum_pnl(result.daily_pnl), literal_total_return, 1e-4);
}
