/**
 * @file   simplex.hpp
 * @brief  Simplex projection and weight normalization helpers.
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <numeric>
#include <vector>

namespace zinc::opt::detail {

inline std::vector<double> project_simplex(std::vector<double> vector) {
    const std::size_t count = vector.size();
    if (count == 0) {
        return {};
    }

    std::vector<double> sorted = vector;
    std::sort(sorted.begin(), sorted.end(), std::greater<double>());

    double cumulative = 0.0;
    std::size_t rho = 0;
    for (std::size_t index = 0; index < count; ++index) {
        cumulative += sorted[index];
        const double threshold = (cumulative - 1.0) / static_cast<double>(index + 1);
        if (sorted[index] > threshold) {
            rho = index;
        }
    }

    const double theta = (std::accumulate(sorted.begin(), sorted.begin() + static_cast<std::ptrdiff_t>(rho + 1),
                                          0.0) -
                          1.0) /
                         static_cast<double>(rho + 1);

    for (double& value : vector) {
        value = std::max(0.0, value - theta);
    }

    return vector;
}

inline std::vector<double> normalize_weights(std::vector<double> weights) {
    double sum = 0.0;
    for (const double weight : weights) {
        if (weight > 0.0) {
            sum += weight;
        }
    }
    if (sum <= 0.0) {
        const std::size_t count = weights.size();
        if (count == 0) {
            return weights;
        }
        const double equal = 1.0 / static_cast<double>(count);
        for (double& weight : weights) {
            weight = equal;
        }
        return weights;
    }

    for (double& weight : weights) {
        weight = std::max(0.0, weight) / sum;
    }
    return weights;
}

inline bool weights_sum_to_one(const std::vector<double>& weights, double tolerance = 1e-9) {
    double sum = 0.0;
    for (const double weight : weights) {
        sum += weight;
    }
    return std::abs(sum - 1.0) <= tolerance;
}

}  // namespace zinc::opt::detail
