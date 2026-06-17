/**
 * @file   opt_bench.cpp
 * @brief  Google Benchmark suite for zinc::opt kernels.
 */

#include "zinc/opt/hrp.hpp"
#include "zinc/opt/mvo.hpp"

#include <Eigen/Dense>

#include <benchmark/benchmark.h>
#include <random>

namespace {

Eigen::MatrixXd make_covariance(const int assets, const std::uint64_t seed) {
    std::mt19937_64 rng(seed);
    std::normal_distribution<double> normal(0.0, 1.0);
    Eigen::MatrixXd factor(assets, assets);
    for (int row = 0; row < assets; ++row) {
        for (int column = 0; column < assets; ++column) {
            factor(row, column) = normal(rng) * 0.05;
        }
    }
    return factor * factor.transpose() + Eigen::MatrixXd::Identity(assets, assets) * 1e-3;
}

const Eigen::MatrixXd kCovariance50 = make_covariance(50, 0x0B7050ULL);
const Eigen::MatrixXd kCovariance100 = make_covariance(100, 0x0B7100ULL);
const Eigen::VectorXd kExpectedReturns50 = Eigen::VectorXd::Zero(50);

} // namespace

static void BM_mvo_50_assets(benchmark::State& state) {
    for (auto _ : state) {
        const auto weights = zinc::opt::mvo(kExpectedReturns50, kCovariance50, 1.0);
        benchmark::DoNotOptimize(weights);
    }
}
BENCHMARK(BM_mvo_50_assets);

static void BM_hrp_100_assets(benchmark::State& state) {
    for (auto _ : state) {
        const auto weights = zinc::opt::hrp(kCovariance100);
        benchmark::DoNotOptimize(weights);
    }
}
BENCHMARK(BM_hrp_100_assets);

BENCHMARK_MAIN();
