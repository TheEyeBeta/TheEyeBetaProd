/**
 * @file   hmm_regime.cpp
 * @brief  Gaussian HMM regime detection (Baum–Welch + Viterbi).
 */

#include "zinc/ta/hmm_regime.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <numbers>
#include <numeric>
#include <span>
#include <vector>

namespace zinc::ta {

namespace {

constexpr int kNumStates = 2;
constexpr double kVarianceFloor = 1e-6;
constexpr double kLogZero = -1e300;

double log_sum_exp(double left, double right) {
    if (left == kLogZero) {
        return right;
    }
    if (right == kLogZero) {
        return left;
    }
    const double maximum = std::max(left, right);
    return maximum + std::log(std::exp(left - maximum) + std::exp(right - maximum));
}

double gaussian_log_pdf(double observation, double mean, double variance) {
    const double adjusted_variance = std::max(variance, kVarianceFloor);
    const double delta = observation - mean;
    return -0.5 * (std::log(2.0 * std::numbers::pi * adjusted_variance) +
                   (delta * delta) / adjusted_variance);
}

struct GaussianHmm {
    std::array<double, kNumStates> initial_log{std::log(0.5), std::log(0.5)};
    std::array<std::array<double, kNumStates>, kNumStates> transition_log{};
    std::array<double, kNumStates> means{};
    std::array<double, kNumStates> variances{};
};

void initialize_model(GaussianHmm& model, std::span<const double> observations) {
    std::vector<double> sorted(observations.begin(), observations.end());
    std::sort(sorted.begin(), sorted.end());
    const double median = sorted[sorted.size() / 2];

    double low_sum = 0.0;
    double high_sum = 0.0;
    std::size_t low_count = 0;
    std::size_t high_count = 0;
    for (const double value : observations) {
        if (value <= median) {
            low_sum += value;
            ++low_count;
        } else {
            high_sum += value;
            ++high_count;
        }
    }

    model.means[0] = low_count > 0 ? low_sum / static_cast<double>(low_count) : median - 1.0;
    model.means[1] = high_count > 0 ? high_sum / static_cast<double>(high_count) : median + 1.0;

    double global_variance = 0.0;
    const double global_mean =
        std::accumulate(observations.begin(), observations.end(), 0.0) /
        static_cast<double>(observations.size());
    for (const double value : observations) {
        const double delta = value - global_mean;
        global_variance += delta * delta;
    }
    global_variance /= static_cast<double>(observations.size());
    const double split_variance = std::max(global_variance * 0.25, kVarianceFloor);
    model.variances = {split_variance, split_variance};

    for (int row = 0; row < kNumStates; ++row) {
        for (int column = 0; column < kNumStates; ++column) {
            model.transition_log[static_cast<std::size_t>(row)]
                                 [static_cast<std::size_t>(column)] =
                row == column ? std::log(0.95) : std::log(0.05);
        }
    }
}

bool baum_welch(GaussianHmm& model, std::span<const double> observations, int max_iter) {
    const std::size_t length = observations.size();
    if (length < 3) {
        return false;
    }

    std::vector<std::vector<double>> emission_log(length,
                                                  std::vector<double>(kNumStates, kLogZero));
    for (std::size_t time = 0; time < length; ++time) {
        for (int state = 0; state < kNumStates; ++state) {
            emission_log[time][static_cast<std::size_t>(state)] = gaussian_log_pdf(
                observations[time], model.means[static_cast<std::size_t>(state)],
                model.variances[static_cast<std::size_t>(state)]);
        }
    }

    for (int iteration = 0; iteration < max_iter; ++iteration) {
        std::vector<std::vector<double>> alpha(length, std::vector<double>(kNumStates, kLogZero));
        std::vector<double> scale(length, 0.0);

        for (int state = 0; state < kNumStates; ++state) {
            alpha[0][static_cast<std::size_t>(state)] =
                model.initial_log[static_cast<std::size_t>(state)] +
                emission_log[0][static_cast<std::size_t>(state)];
        }
        scale[0] = alpha[0][0];
        for (int state = 1; state < kNumStates; ++state) {
            scale[0] = log_sum_exp(scale[0], alpha[0][static_cast<std::size_t>(state)]);
        }
        for (int state = 0; state < kNumStates; ++state) {
            alpha[0][static_cast<std::size_t>(state)] -= scale[0];
        }

        for (std::size_t time = 1; time < length; ++time) {
            for (int state = 0; state < kNumStates; ++state) {
                double total = kLogZero;
                for (int previous = 0; previous < kNumStates; ++previous) {
                    const double candidate =
                        alpha[time - 1][static_cast<std::size_t>(previous)] +
                        model.transition_log[static_cast<std::size_t>(previous)]
                                            [static_cast<std::size_t>(state)] +
                        emission_log[time][static_cast<std::size_t>(state)];
                    total = log_sum_exp(total, candidate);
                }
                alpha[time][static_cast<std::size_t>(state)] = total;
            }
            scale[time] = alpha[time][0];
            for (int state = 1; state < kNumStates; ++state) {
                scale[time] =
                    log_sum_exp(scale[time], alpha[time][static_cast<std::size_t>(state)]);
            }
            for (int state = 0; state < kNumStates; ++state) {
                alpha[time][static_cast<std::size_t>(state)] -= scale[time];
            }
        }

        std::vector<std::vector<double>> beta(length, std::vector<double>(kNumStates, kLogZero));
        for (int state = 0; state < kNumStates; ++state) {
            beta[length - 1][static_cast<std::size_t>(state)] = 0.0;
        }

        for (int time = static_cast<int>(length) - 2; time >= 0; --time) {
            const std::size_t time_index = static_cast<std::size_t>(time);
            const std::size_t next_index = time_index + 1;
            for (int state = 0; state < kNumStates; ++state) {
                double total = kLogZero;
                for (int next = 0; next < kNumStates; ++next) {
                    const double candidate =
                        model.transition_log[static_cast<std::size_t>(state)]
                                            [static_cast<std::size_t>(next)] +
                        emission_log[next_index][static_cast<std::size_t>(next)] +
                        beta[next_index][static_cast<std::size_t>(next)];
                    total = log_sum_exp(total, candidate);
                }
                beta[time_index][static_cast<std::size_t>(state)] = total - scale[next_index];
            }
        }

        std::vector<std::vector<double>> gamma(length, std::vector<double>(kNumStates, 0.0));
        std::array<std::array<double, kNumStates>, kNumStates> xi{};
        for (auto& row : xi) {
            row.fill(0.0);
        }

        for (std::size_t time = 0; time < length; ++time) {
            double normalizer = kLogZero;
            for (int state = 0; state < kNumStates; ++state) {
                normalizer = log_sum_exp(normalizer, alpha[time][static_cast<std::size_t>(state)] +
                                                      beta[time][static_cast<std::size_t>(state)]);
            }

            for (int state = 0; state < kNumStates; ++state) {
                gamma[time][static_cast<std::size_t>(state)] = std::exp(
                    alpha[time][static_cast<std::size_t>(state)] +
                    beta[time][static_cast<std::size_t>(state)] - normalizer);
            }

            if (time + 1 < length) {
                double xi_normalizer = kLogZero;
                for (int from_state = 0; from_state < kNumStates; ++from_state) {
                    for (int to_state = 0; to_state < kNumStates; ++to_state) {
                        const double value =
                            alpha[time][static_cast<std::size_t>(from_state)] +
                            model.transition_log[static_cast<std::size_t>(from_state)]
                                                [static_cast<std::size_t>(to_state)] +
                            emission_log[time + 1][static_cast<std::size_t>(to_state)] +
                            beta[time + 1][static_cast<std::size_t>(to_state)];
                        xi_normalizer = log_sum_exp(xi_normalizer, value);
                    }
                }

                for (int from_state = 0; from_state < kNumStates; ++from_state) {
                    for (int to_state = 0; to_state < kNumStates; ++to_state) {
                        const double value =
                            alpha[time][static_cast<std::size_t>(from_state)] +
                            model.transition_log[static_cast<std::size_t>(from_state)]
                                                [static_cast<std::size_t>(to_state)] +
                            emission_log[time + 1][static_cast<std::size_t>(to_state)] +
                            beta[time + 1][static_cast<std::size_t>(to_state)] - xi_normalizer;
                        xi[static_cast<std::size_t>(from_state)][static_cast<std::size_t>(to_state)] +=
                            std::exp(value);
                    }
                }
            }
        }

        const double initial_gamma_0 = gamma[0][0];
        const double initial_gamma_1 = gamma[0][1];
        const double initial_sum = initial_gamma_0 + initial_gamma_1;
        if (initial_sum > 0.0) {
            model.initial_log[0] = std::log(initial_gamma_0 / initial_sum);
            model.initial_log[1] = std::log(initial_gamma_1 / initial_sum);
        }

        for (int from_state = 0; from_state < kNumStates; ++from_state) {
            double row_sum = 0.0;
            for (int to_state = 0; to_state < kNumStates; ++to_state) {
                row_sum += xi[static_cast<std::size_t>(from_state)][static_cast<std::size_t>(to_state)];
            }
            if (row_sum > 0.0) {
                for (int to_state = 0; to_state < kNumStates; ++to_state) {
                    model.transition_log[static_cast<std::size_t>(from_state)]
                                        [static_cast<std::size_t>(to_state)] =
                        std::log(xi[static_cast<std::size_t>(from_state)]
                                           [static_cast<std::size_t>(to_state)] /
                                 row_sum);
                }
            }
        }

        for (int state = 0; state < kNumStates; ++state) {
            double weight_sum = 0.0;
            double weighted_mean = 0.0;
            double weighted_sq = 0.0;
            for (std::size_t time = 0; time < length; ++time) {
                const double weight = gamma[time][static_cast<std::size_t>(state)];
                weight_sum += weight;
                weighted_mean += weight * observations[time];
            }
            if (weight_sum <= 0.0) {
                continue;
            }
            weighted_mean /= weight_sum;
            for (std::size_t time = 0; time < length; ++time) {
                const double weight = gamma[time][static_cast<std::size_t>(state)];
                const double delta = observations[time] - weighted_mean;
                weighted_sq += weight * delta * delta;
            }
            model.means[static_cast<std::size_t>(state)] = weighted_mean;
            model.variances[static_cast<std::size_t>(state)] =
                std::max(weighted_sq / weight_sum, kVarianceFloor);
        }
    }

    return true;
}

std::vector<int> viterbi_decode(const GaussianHmm& model, std::span<const double> observations) {
    const std::size_t length = observations.size();
    std::vector<std::vector<double>> delta(length, std::vector<double>(kNumStates, kLogZero));
    std::vector<std::vector<int>> psi(length, std::vector<int>(kNumStates, 0));

    for (int state = 0; state < kNumStates; ++state) {
        delta[0][static_cast<std::size_t>(state)] =
            model.initial_log[static_cast<std::size_t>(state)] +
            gaussian_log_pdf(observations[0], model.means[static_cast<std::size_t>(state)],
                             model.variances[static_cast<std::size_t>(state)]);
    }

    for (std::size_t time = 1; time < length; ++time) {
        for (int state = 0; state < kNumStates; ++state) {
            double best_score = kLogZero;
            int best_state = 0;
            for (int previous = 0; previous < kNumStates; ++previous) {
                const double candidate =
                    delta[time - 1][static_cast<std::size_t>(previous)] +
                    model.transition_log[static_cast<std::size_t>(previous)]
                                        [static_cast<std::size_t>(state)];
                if (candidate > best_score) {
                    best_score = candidate;
                    best_state = previous;
                }
            }
            psi[time][static_cast<std::size_t>(state)] = best_state;
            delta[time][static_cast<std::size_t>(state)] =
                best_score + gaussian_log_pdf(observations[time],
                                              model.means[static_cast<std::size_t>(state)],
                                              model.variances[static_cast<std::size_t>(state)]);
        }
    }

    int best_final_state = 0;
    double best_final_score = delta[length - 1][0];
    for (int state = 1; state < kNumStates; ++state) {
        if (delta[length - 1][static_cast<std::size_t>(state)] > best_final_score) {
            best_final_score = delta[length - 1][static_cast<std::size_t>(state)];
            best_final_state = state;
        }
    }

    std::vector<int> path(length);
    path[length - 1] = best_final_state;
    for (int time = static_cast<int>(length) - 2; time >= 0; --time) {
        const std::size_t time_index = static_cast<std::size_t>(time);
        path[time_index] =
            psi[time_index + 1][static_cast<std::size_t>(path[time_index + 1])];
    }

    return path;
}

}  // namespace

HmmRegimeResult hmm_regime(std::span<const double> observations, int n_states, int max_iter) {
    HmmRegimeResult result;
    if (n_states != kNumStates || observations.size() < 3 || max_iter < 1) {
        return result;
    }

    GaussianHmm model;
    initialize_model(model, observations);
    if (!baum_welch(model, observations, max_iter)) {
        return result;
    }

    result.states = viterbi_decode(model, observations);
    return result;
}

}  // namespace zinc::ta
