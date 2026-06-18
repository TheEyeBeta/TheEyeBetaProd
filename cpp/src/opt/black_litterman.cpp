/**
 * @file   black_litterman.cpp
 * @brief  Black–Litterman posterior weights.
 */

#include "zinc/opt/black_litterman.hpp"

#include "zinc/opt/mvo.hpp"

#include <cmath>

namespace zinc::opt {

PortfolioWeights black_litterman(const Eigen::Ref<const Eigen::MatrixXd>& covariance,
                                 const Eigen::Ref<const Eigen::VectorXd>& market_weights,
                                 const Eigen::Ref<const Eigen::MatrixXd>& picking_matrix,
                                 const Eigen::Ref<const Eigen::VectorXd>& view_returns,
                                 const Eigen::Ref<const Eigen::VectorXd>& view_uncertainty,
                                 const double risk_aversion, const double tau,
                                 const bool long_only) {
    PortfolioWeights result;
    const Eigen::Index assets = covariance.rows();
    const Eigen::Index views = picking_matrix.rows();

    if (assets == 0 || covariance.cols() != assets || market_weights.size() != assets ||
        picking_matrix.cols() != assets || view_returns.size() != views ||
        view_uncertainty.size() != views || risk_aversion <= 0.0 || tau <= 0.0) {
        return result;
    }

    for (Eigen::Index index = 0; index < views; ++index) {
        if (view_uncertainty(index) <= 0.0 || !std::isfinite(view_uncertainty(index))) {
            return result;
        }
    }

    const Eigen::VectorXd equilibrium_returns = risk_aversion * covariance * market_weights;
    const Eigen::MatrixXd scaled_covariance = tau * covariance;
    const Eigen::MatrixXd precision_prior = scaled_covariance.inverse();

    Eigen::MatrixXd omega = Eigen::MatrixXd::Zero(views, views);
    for (Eigen::Index index = 0; index < views; ++index) {
        omega(index, index) = 1.0 / view_uncertainty(index);
    }

    const Eigen::MatrixXd posterior_precision =
        precision_prior + picking_matrix.transpose() * omega * picking_matrix;
    const Eigen::VectorXd posterior_returns =
        posterior_precision.inverse() *
        (precision_prior * equilibrium_returns + picking_matrix.transpose() * omega * view_returns);

    return mvo(posterior_returns, covariance, risk_aversion, long_only);
}

} // namespace zinc::opt
