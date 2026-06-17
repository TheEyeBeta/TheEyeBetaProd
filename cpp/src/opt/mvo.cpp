/**
 * @file   mvo.cpp
 * @brief  Mean–variance (Markowitz) portfolio optimization.
 */

#include "zinc/opt/mvo.hpp"

#include "zinc/opt/detail/simplex.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

namespace zinc::opt {

namespace {

constexpr int kMaxIterations = 2000;
constexpr double kTolerance = 1e-10;
constexpr double kInitialStep = 0.1;

} // namespace

PortfolioWeights mvo(const Eigen::Ref<const Eigen::VectorXd>& expected_returns,
                     const Eigen::Ref<const Eigen::MatrixXd>& covariance,
                     const double risk_aversion, const bool long_only) {
    PortfolioWeights result;
    const Eigen::Index assets = expected_returns.size();
    if (assets == 0 || covariance.rows() != assets || covariance.cols() != assets ||
        risk_aversion <= 0.0 || !std::isfinite(risk_aversion)) {
        return result;
    }

    if (assets == 1) {
        result.weights = {1.0};
        return result;
    }

    std::vector<double> weights(static_cast<std::size_t>(assets),
                                1.0 / static_cast<double>(assets));
    double step = kInitialStep;

    for (int iteration = 0; iteration < kMaxIterations; ++iteration) {
        Eigen::Map<Eigen::VectorXd> weight_map(weights.data(), assets);
        const Eigen::VectorXd gradient = expected_returns - risk_aversion * covariance * weight_map;

        std::vector<double> candidate = weights;
        for (Eigen::Index index = 0; index < assets; ++index) {
            candidate[static_cast<std::size_t>(index)] += step * gradient(index);
        }

        if (long_only) {
            candidate = detail::project_simplex(std::move(candidate));
        } else {
            candidate = detail::normalize_weights(std::move(candidate));
        }

        double change = 0.0;
        for (std::size_t index = 0; index < weights.size(); ++index) {
            change = std::max(change, std::abs(weights[index] - candidate[index]));
        }

        weights = std::move(candidate);
        if (change < kTolerance) {
            break;
        }

        if (iteration % 50 == 49) {
            step *= 0.9;
        }
    }

    if (long_only) {
        weights = detail::project_simplex(std::move(weights));
    } else {
        weights = detail::normalize_weights(std::move(weights));
    }

    result.weights = std::move(weights);
    return result;
}

} // namespace zinc::opt
