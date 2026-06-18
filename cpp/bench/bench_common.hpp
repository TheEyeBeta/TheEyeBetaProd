/**
 * @file   bench_common.hpp
 * @brief  Shared helpers for zinc microbenchmarks.
 */

#pragma once

#include "zinc/ta/bar.hpp"

#include <cmath>
#include <cstdint>
#include <vector>

#include <random>

namespace zinc::bench {

inline std::vector<double> make_returns(const std::size_t count, const std::uint64_t seed) {
    std::mt19937_64 rng(seed);
    std::normal_distribution<double> normal(0.0, 0.01);
    std::vector<double> values(count);
    for (double& value : values) {
        value = normal(rng);
    }
    return values;
}

inline std::vector<zinc::ta::Bar> make_ohlc_bars(const std::size_t count,
                                                 const std::uint64_t seed) {
    std::mt19937_64 rng(seed);
    std::normal_distribution<double> normal(0.0, 0.5);
    std::vector<zinc::ta::Bar> bars(count);
    double close = 100.0;
    for (std::size_t index = 0; index < count; ++index) {
        close = std::max(1.0, close + normal(rng));
        const double open = close - normal(rng) * 0.1;
        const double high = std::max(open, close) + std::abs(normal(rng));
        const double low = std::min(open, close) - std::abs(normal(rng));
        bars[index] = zinc::ta::Bar{.open = open, .high = high, .low = low, .close = close};
    }
    return bars;
}

} // namespace zinc::bench
