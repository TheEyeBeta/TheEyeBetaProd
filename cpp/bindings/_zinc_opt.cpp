/**
 * @file   _zinc_opt.cpp
 * @brief  nanobind bindings for zinc::opt kernels.
 */

#include "zinc/opt/black_litterman.hpp"
#include "zinc/opt/hrp.hpp"
#include "zinc/opt/mvo.hpp"
#include "zinc/opt/portfolio_weights.hpp"

#include <stdexcept>

#include <Eigen/Dense>
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/vector.h>

namespace nb = nanobind;

namespace {

using ContiguousVector = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using ContiguousMatrix = nb::ndarray<const double, nb::ndim<2>, nb::c_contig>;

Eigen::Map<const Eigen::VectorXd> as_vector(const ContiguousVector& array) {
    if (array.ndim() != 1) {
        throw std::invalid_argument("array must be one-dimensional");
    }
    return Eigen::Map<const Eigen::VectorXd>(array.data(),
                                             static_cast<Eigen::Index>(array.shape(0)));
}

Eigen::Map<const Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>>
as_matrix(const ContiguousMatrix& array) {
    if (array.ndim() != 2) {
        throw std::invalid_argument("array must be two-dimensional");
    }
    return Eigen::Map<const Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>>(
        array.data(), static_cast<Eigen::Index>(array.shape(0)),
        static_cast<Eigen::Index>(array.shape(1)));
}

} // namespace

NB_MODULE(_zinc_opt, module) {
    module.doc() = "zinc::opt — Markowitz MVO, Black–Litterman, and HRP portfolio weights";

    nb::class_<zinc::opt::PortfolioWeights>(module, "PortfolioWeights",
                                            "Portfolio weights that sum to one.")
        .def_prop_ro(
            "weights",
            [](const zinc::opt::PortfolioWeights& portfolio) {
                return nb::cast(portfolio.weights);
            },
            "Asset weights as a C-contiguous float64 vector.");

    module.def(
        "mvo",
        [](const ContiguousVector& expected_returns, const ContiguousMatrix& covariance,
           double risk_aversion, bool long_only) {
            const Eigen::Index assets = as_vector(expected_returns).size();
            const auto covariance_map = as_matrix(covariance);
            if (covariance_map.rows() != assets || covariance_map.cols() != assets) {
                throw std::invalid_argument(
                    "covariance must be square with side equal to len(expected_returns)");
            }
            return zinc::opt::mvo(as_vector(expected_returns), covariance_map, risk_aversion,
                                  long_only);
        },
        nb::arg("expected_returns"), nb::arg("covariance"), nb::arg("risk_aversion") = 1.0,
        nb::arg("long_only") = true,
        R"doc(
Long-only mean–variance optimal portfolio (Markowitz).

Maximizes mu^T w - (lambda/2) w^T Sigma w subject to sum(w) = 1 and w >= 0 when
long_only is true. Weights sum to 1.0.
)doc");

    module.def(
        "black_litterman",
        [](const ContiguousMatrix& covariance, const ContiguousVector& market_weights,
           const ContiguousMatrix& picking_matrix, const ContiguousVector& view_returns,
           const ContiguousVector& view_uncertainty, double risk_aversion, double tau,
           bool long_only) {
            const auto covariance_map = as_matrix(covariance);
            const Eigen::Index assets = covariance_map.rows();
            if (covariance_map.cols() != assets) {
                throw std::invalid_argument("covariance must be square");
            }
            if (as_vector(market_weights).size() != assets) {
                throw std::invalid_argument("market_weights length must match covariance size");
            }
            const auto picking_map = as_matrix(picking_matrix);
            if (picking_map.cols() != assets) {
                throw std::invalid_argument("picking_matrix columns must match covariance size");
            }
            const Eigen::Index views = picking_map.rows();
            if (as_vector(view_returns).size() != views ||
                as_vector(view_uncertainty).size() != views) {
                throw std::invalid_argument(
                    "view_returns and view_uncertainty length must match picking_matrix rows");
            }
            return zinc::opt::black_litterman(
                covariance_map, as_vector(market_weights), picking_map, as_vector(view_returns),
                as_vector(view_uncertainty), risk_aversion, tau, long_only);
        },
        nb::arg("covariance"), nb::arg("market_weights"), nb::arg("picking_matrix"),
        nb::arg("view_returns"), nb::arg("view_uncertainty"), nb::arg("risk_aversion") = 2.5,
        nb::arg("tau") = 0.05, nb::arg("long_only") = true,
        R"doc(
Black–Litterman optimal portfolio weights.

Combines equilibrium prior pi = delta Sigma w_mkt with investor views P mu = Q to obtain
posterior expected returns, then solves the same long-only MVO problem as mvo.
)doc");

    module.def(
        "hrp",
        [](const ContiguousMatrix& covariance) {
            const auto covariance_map = as_matrix(covariance);
            if (covariance_map.rows() != covariance_map.cols()) {
                throw std::invalid_argument("covariance must be square");
            }
            return zinc::opt::hrp(covariance_map);
        },
        nb::arg("covariance"),
        R"doc(
Hierarchical Risk Parity weights via recursive bisection.

Builds a correlation-distance linkage tree, quasi-diagonalizes the covariance, then
allocates mass recursively between clusters. Weights are long-only and sum to one.
)doc");
}
