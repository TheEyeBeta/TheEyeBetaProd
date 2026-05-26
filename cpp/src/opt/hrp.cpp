/**
 * @file   hrp.cpp
 * @brief  Hierarchical Risk Parity implementation.
 */

#include "zinc/opt/hrp.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <utility>
#include <vector>

#include "zinc/opt/detail/simplex.hpp"

namespace zinc::opt {

namespace {

double cluster_variance(const Eigen::MatrixXd& covariance, const std::vector<int>& indices) {
    const int count = static_cast<int>(indices.size());
    if (count == 0) {
        return 0.0;
    }
    if (count == 1) {
        return covariance(indices.front(), indices.front());
    }

    Eigen::MatrixXd sub_cov(count, count);
    for (int row = 0; row < count; ++row) {
        for (int column = 0; column < count; ++column) {
            sub_cov(row, column) = covariance(indices[static_cast<std::size_t>(row)],
                                              indices[static_cast<std::size_t>(column)]);
        }
    }

    Eigen::VectorXd inverse_variance(count);
    for (int index = 0; index < count; ++index) {
        const double variance = sub_cov(index, index);
        inverse_variance(index) = variance > 0.0 ? 1.0 / variance : 0.0;
    }

    const double sum = inverse_variance.sum();
    if (sum <= 0.0) {
        return 0.0;
    }
    const Eigen::VectorXd weights = inverse_variance / sum;
    return (weights.transpose() * sub_cov * weights).value();
}

void recursive_bisection(const Eigen::MatrixXd& covariance, const std::vector<int>& order,
                         std::vector<double>& weights, std::size_t begin, std::size_t end,
                         double mass) {
    const std::size_t count = end - begin;
    if (count == 0) {
        return;
    }
    if (count == 1) {
        weights[static_cast<std::size_t>(order[begin])] = mass;
        return;
    }

    const std::size_t mid = begin + count / 2;
    std::vector<int> left(order.begin() + static_cast<std::ptrdiff_t>(begin),
                          order.begin() + static_cast<std::ptrdiff_t>(mid));
    std::vector<int> right(order.begin() + static_cast<std::ptrdiff_t>(mid),
                           order.begin() + static_cast<std::ptrdiff_t>(end));

    const double left_variance = cluster_variance(covariance, left);
    const double right_variance = cluster_variance(covariance, right);
    const double denominator = left_variance + right_variance;
    const double left_share =
        denominator > 0.0 ? 1.0 - left_variance / denominator : 0.5;

    recursive_bisection(covariance, order, weights, begin, mid, mass * left_share);
    recursive_bisection(covariance, order, weights, mid, end, mass * (1.0 - left_share));
}

double correlation_distance(const Eigen::MatrixXd& covariance, int left, int right) {
    const double left_variance = covariance(left, left);
    const double right_variance = covariance(right, right);
    if (left_variance <= 0.0 || right_variance <= 0.0) {
        return 1.0;
    }
    const double correlation =
        covariance(left, right) / std::sqrt(left_variance * right_variance);
    const double clamped = std::clamp(correlation, -1.0, 1.0);
    return std::sqrt(0.5 * (1.0 - clamped));
}

std::vector<int> quasi_diagonal_order(const Eigen::MatrixXd& covariance) {
    const int assets = static_cast<int>(covariance.rows());
    std::vector<std::vector<int>> clusters(static_cast<std::size_t>(assets));
    for (int index = 0; index < assets; ++index) {
        clusters[static_cast<std::size_t>(index)] = {index};
    }

    while (clusters.size() > 1) {
        double best_distance = std::numeric_limits<double>::infinity();
        std::size_t best_left = 0;
        std::size_t best_right = 1;

        for (std::size_t left = 0; left < clusters.size(); ++left) {
            for (std::size_t right = left + 1; right < clusters.size(); ++right) {
                double minimum = std::numeric_limits<double>::infinity();
                for (const int left_index : clusters[left]) {
                    for (const int right_index : clusters[right]) {
                        minimum = std::min(minimum,
                                           correlation_distance(covariance, left_index,
                                                                right_index));
                    }
                }
                if (minimum < best_distance) {
                    best_distance = minimum;
                    best_left = left;
                    best_right = right;
                }
            }
        }

        std::vector<int> merged = clusters[best_left];
        merged.insert(merged.end(), clusters[best_right].begin(), clusters[best_right].end());
        clusters.erase(clusters.begin() + static_cast<std::ptrdiff_t>(best_right));
        clusters[best_left] = std::move(merged);
    }

    return clusters.front();
}

}  // namespace

PortfolioWeights hrp(const Eigen::Ref<const Eigen::MatrixXd>& covariance) {
    PortfolioWeights result;
    const Eigen::Index assets = covariance.rows();
    if (assets == 0 || covariance.cols() != assets) {
        return result;
    }

    if (assets == 1) {
        result.weights = {1.0};
        return result;
    }

    const std::vector<int> order = quasi_diagonal_order(covariance);
    std::vector<double> weights(static_cast<std::size_t>(assets), 0.0);
    recursive_bisection(covariance, order, weights, 0, static_cast<std::size_t>(assets), 1.0);
    result.weights = detail::normalize_weights(std::move(weights));
    return result;
}

}  // namespace zinc::opt
