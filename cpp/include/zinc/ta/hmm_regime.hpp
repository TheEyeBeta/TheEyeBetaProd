/**
 * @file   hmm_regime.hpp
 * @brief  Gaussian HMM regime detection (Baum–Welch + Viterbi).
 */

#pragma once

#include <cstddef>
#include <span>
#include <vector>

namespace zinc::ta {

/**
 * @brief Decoded hidden states from a Gaussian HMM.
 */
struct HmmRegimeResult {
    /** @brief Viterbi state index per observation (0 .. n_states-1). */
    std::vector<int> states;
};

/**
 * @brief Fit a Gaussian HMM and decode the most likely regime path.
 *
 * Uses Baum–Welch (EM) parameter estimation and Viterbi decoding. Currently
 * supports @p n_states @c == 2 only.
 *
 * @param observations Univariate observation series.
 * @param n_states     Number of hidden states (must be @c 2).
 * @param max_iter     Maximum Baum–Welch iterations (default @c 100).
 *
 * @return Decoded state sequence, or empty when ill-conditioned / invalid input.
 *
 * @pre @p observations.size() &ge; 3 and @p n_states @c == 2.
 *
 * @example
 * @code
 * const auto regimes = zinc::ta::hmm_regime(returns, 2);
 * @endcode
 */
[[nodiscard]] HmmRegimeResult hmm_regime(std::span<const double> observations, int n_states = 2,
                                         int max_iter = 100);

}  // namespace zinc::ta
