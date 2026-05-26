/**
 * @file   ta_bench.cpp
 * @brief  Google Benchmark suite for zinc::ta kernels.
 */

#include <vector>

#include <benchmark/benchmark.h>

#include "bench_common.hpp"
#include "zinc/ta/adx.hpp"
#include "zinc/ta/atr.hpp"
#include "zinc/ta/hmm_regime.hpp"

namespace {

constexpr int kPeriod = 14;
const std::vector<zinc::ta::Bar> kBars = zinc::bench::make_ohlc_bars(1'000, 0xTA1KBAR);
const std::vector<double> kObservations = zinc::bench::make_returns(500, 0xTA500);

}  // namespace

static void BM_atr_1k_bars(benchmark::State& state) {
    for (auto _ : state) {
        const std::vector<double> values = zinc::ta::atr(kBars, kPeriod);
        benchmark::DoNotOptimize(values);
    }
}
BENCHMARK(BM_atr_1k_bars);

static void BM_adx_1k_bars(benchmark::State& state) {
    for (auto _ : state) {
        const std::vector<double> values = zinc::ta::adx(kBars, kPeriod);
        benchmark::DoNotOptimize(values);
    }
}
BENCHMARK(BM_adx_1k_bars);

static void BM_hmm_regime_500(benchmark::State& state) {
    for (auto _ : state) {
        const zinc::ta::HmmRegimeResult result = zinc::ta::hmm_regime(kObservations, 2);
        benchmark::DoNotOptimize(result);
    }
}
BENCHMARK(BM_hmm_regime_500);

BENCHMARK_MAIN();
