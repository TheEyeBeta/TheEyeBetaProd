/**
 * @file   risk_bench.cpp
 * @brief  Google Benchmark suite for zinc::risk kernels.
 */

#include "bench_common.hpp"
#include "zinc/risk/correlation_matrix.hpp"
#include "zinc/risk/historical_var.hpp"

#include <vector>

#include <Eigen/Dense>

#include <benchmark/benchmark.h>
#include <random>

namespace {

const std::vector<double> kReturns = zinc::bench::make_returns(10'000, 0xB15C1ULL);
const Eigen::MatrixXd kCorrelationData = []() {
    Eigen::MatrixXd matrix(252, 100);
    std::mt19937_64 rng(0xC0C252ULL);
    std::normal_distribution<double> normal(0.0, 1.0);
    for (Eigen::Index row = 0; row < matrix.rows(); ++row) {
        for (Eigen::Index column = 0; column < matrix.cols(); ++column) {
            matrix(row, column) = normal(rng);
        }
    }
    return matrix;
}();

} // namespace

static void BM_historical_var_10k(benchmark::State& state) {
    for (auto _ : state) {
        const double value = zinc::risk::historical_var(kReturns, 0.05);
        benchmark::DoNotOptimize(value);
    }
}
BENCHMARK(BM_historical_var_10k);

static void BM_correlation_matrix_100x252(benchmark::State& state) {
    for (auto _ : state) {
        const Eigen::MatrixXd result = zinc::risk::correlation_matrix(kCorrelationData);
        benchmark::DoNotOptimize(result);
    }
}
BENCHMARK(BM_correlation_matrix_100x252);

BENCHMARK_MAIN();
