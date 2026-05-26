/**
 * @file   ta_hmm_regime_test.cpp
 * @brief  Unit tests for zinc::ta::hmm_regime.
 */

#include "zinc/ta/hmm_regime.hpp"

#include <cmath>
#include <cstdint>
#include <random>
#include <vector>

#include <gtest/gtest.h>

namespace {

struct SyntheticHmm {
    std::vector<int> true_states;
    std::vector<double> observations;
};

SyntheticHmm make_synthetic_two_regime(std::size_t length, std::uint64_t seed) {
    SyntheticHmm data;
    data.true_states.reserve(length);
    data.observations.reserve(length);

    std::mt19937_64 rng(seed);
    std::normal_distribution<double> low_regime(0.0, 0.3);
    std::normal_distribution<double> high_regime(3.0, 0.3);
    std::uniform_real_distribution<double> transition(0.0, 1.0);

    int state = 0;
    for (std::size_t index = 0; index < length; ++index) {
        if (index > 0 && transition(rng) < 0.05) {
            state = 1 - state;
        }
        data.true_states.push_back(state);
        data.observations.push_back(state == 0 ? low_regime(rng) : high_regime(rng));
    }

    return data;
}

double regime_accuracy(const std::vector<int>& predicted, const std::vector<int>& truth) {
    if (predicted.size() != truth.size() || predicted.empty()) {
        return 0.0;
    }

    std::size_t direct_matches = 0;
    std::size_t flipped_matches = 0;
    for (std::size_t index = 0; index < truth.size(); ++index) {
        if (predicted[index] == truth[index]) {
            ++direct_matches;
        }
        if (predicted[index] == (1 - truth[index])) {
            ++flipped_matches;
        }
    }

    const double direct_rate =
        static_cast<double>(direct_matches) / static_cast<double>(truth.size());
    const double flipped_rate =
        static_cast<double>(flipped_matches) / static_cast<double>(truth.size());
    return std::max(direct_rate, flipped_rate);
}

}  // namespace

TEST(TaHmmRegimeTest, HappyPathRecoversSyntheticRegimesAboveEightyFivePercent) {
    const SyntheticHmm data = make_synthetic_two_regime(500, 42U);
    const auto result = zinc::ta::hmm_regime(data.observations, 2, 100);
    ASSERT_EQ(result.states.size(), data.observations.size());
    EXPECT_GT(regime_accuracy(result.states, data.true_states), 0.85);
}

TEST(TaHmmRegimeTest, EmptyAndInvalidInputReturnsEmpty) {
    EXPECT_TRUE(zinc::ta::hmm_regime({}, 2).states.empty());
    EXPECT_TRUE(zinc::ta::hmm_regime({1.0, 2.0}, 2).states.empty());
    EXPECT_TRUE(zinc::ta::hmm_regime({1.0, 2.0, 3.0}, 3).states.empty());
}

TEST(TaHmmRegimeTest, SingleRegimeClusterStillReturnsStates) {
    const std::vector<double> observations{1.0, 1.1, 0.9, 1.05, 0.95};
    const auto result = zinc::ta::hmm_regime(observations, 2, 50);
    ASSERT_EQ(result.states.size(), observations.size());
    for (const int state : result.states) {
        EXPECT_TRUE(state == 0 || state == 1);
    }
}

TEST(TaHmmRegimeTest, SeparatedRegimesHighAccuracyOnLongSeries) {
    std::vector<double> observations;
    std::vector<int> truth;
    observations.reserve(400);
    truth.reserve(400);
    for (int block = 0; block < 4; ++block) {
        const int state = block % 2;
        for (int index = 0; index < 100; ++index) {
            truth.push_back(state);
            observations.push_back(state == 0 ? -2.0 + 0.01 * static_cast<double>(index % 5)
                                              : 2.0 + 0.01 * static_cast<double>(index % 5));
        }
    }

    const auto result = zinc::ta::hmm_regime(observations, 2, 100);
    EXPECT_GT(regime_accuracy(result.states, truth), 0.85);
}

TEST(TaHmmRegimeTest, NumericalStabilityShiftInvariant) {
    const SyntheticHmm base = make_synthetic_two_regime(300, 99U);
    std::vector<double> shifted = base.observations;
    for (double& value : shifted) {
        value += 1.0e6;
    }

    const auto base_result = zinc::ta::hmm_regime(base.observations, 2, 100);
    const auto shifted_result = zinc::ta::hmm_regime(shifted, 2, 100);
    ASSERT_EQ(base_result.states.size(), shifted_result.states.size());
    EXPECT_GT(regime_accuracy(base_result.states, shifted_result.states), 0.85);
}
