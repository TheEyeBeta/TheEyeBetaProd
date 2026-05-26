/**
 * @file   bt_bench.cpp
 * @brief  Google Benchmark suite for zinc::bt::Engine.
 */

#include <cstdio>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

#include <benchmark/benchmark.h>

#include "bt_test_parquet.hpp"
#include "zinc/bt/engine.hpp"
#include "zinc/bt/slippage_model.hpp"

namespace {

constexpr int kTradingDays = 252;
constexpr int kUniverseSize = 500;

std::filesystem::path prepare_parquet_fixture() {
    static const std::filesystem::path path = []() {
        const std::filesystem::path directory =
            std::filesystem::temp_directory_path() / "zinc_bt_bench";
        std::filesystem::create_directories(directory);
        const std::filesystem::path parquet_path = directory / "daily.parquet";

        std::vector<zinc::bt::test::DailyMarketRow> rows;
        rows.reserve(static_cast<std::size_t>(kTradingDays * kUniverseSize));

        for (int day = 0; day < kTradingDays; ++day) {
            const int month = 1 + day / 28;
            const int day_of_month = 1 + day % 28;
            char date_buffer[11];
            std::snprintf(date_buffer, sizeof(date_buffer), "2024-%02d-%02d", month, day_of_month);

            for (int symbol_index = 0; symbol_index < kUniverseSize; ++symbol_index) {
                zinc::bt::test::DailyMarketRow row;
                row.trade_date = date_buffer;
                row.symbol = "S" + std::to_string(symbol_index);
                row.close = 100.0 + static_cast<double>(symbol_index) * 0.01 +
                            static_cast<double>(day) * 0.001;
                row.open = row.close;
                row.high = row.close;
                row.low = row.close;
                row.volume = 1'000'000;
                row.atr14 = 1.0;
                row.adv = 1.0e9;
                rows.push_back(std::move(row));
            }
        }

        if (!zinc::bt::test::write_daily_parquet(parquet_path, rows)) {
            throw std::runtime_error("failed to write bt benchmark parquet fixture");
        }
        return parquet_path;
    }();
    return path;
}

std::vector<std::string> make_universe() {
    std::vector<std::string> universe;
    universe.reserve(static_cast<std::size_t>(kUniverseSize));
    for (int index = 0; index < kUniverseSize; ++index) {
        universe.push_back("S" + std::to_string(index));
    }
    return universe;
}

const std::filesystem::path kParquetPath = prepare_parquet_fixture();
const std::vector<std::string> kUniverse = make_universe();

}  // namespace

static void BM_bt_engine_252d_500_instruments(benchmark::State& state) {
    for (auto _ : state) {
        zinc::bt::Engine engine("bench", "2024-01-01", "2024-12-31", kUniverse,
                                zinc::bt::SlippageModel{});
        engine.set_parquet_path(kParquetPath);
        engine.set_strategy([](const zinc::bt::Snapshot&) {
            return zinc::bt::Decision{.symbol_index = 0, .target_weight = 1.0};
        });
        const zinc::bt::Result result = engine.run();
        benchmark::DoNotOptimize(result);
    }
}
BENCHMARK(BM_bt_engine_252d_500_instruments);

BENCHMARK_MAIN();
