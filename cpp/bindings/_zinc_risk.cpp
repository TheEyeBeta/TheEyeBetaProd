/**
 * @file   _zinc_risk.cpp
 * @brief  nanobind bindings for zinc::risk kernels.
 */

#include "zinc/risk/correlation_matrix.hpp"
#include "zinc/risk/cvar.hpp"
#include "zinc/risk/historical_var.hpp"
#include "zinc/risk/max_drawdown.hpp"

#include <span>
#include <stdexcept>

#include <Eigen/Dense>
#include <nanobind/eigen/dense.h>
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

namespace nb = nanobind;

namespace {

using ContiguousVector = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using ContiguousMatrix = nb::ndarray<const double, nb::ndim<2>, nb::c_contig>;

std::span<const double> as_span(const ContiguousVector& array) {
    if (array.ndim() != 1) {
        throw std::invalid_argument("samples must be a one-dimensional array");
    }
    return {array.data(), static_cast<std::size_t>(array.shape(0))};
}

} // namespace

/**
 * @brief Pearson correlation matrix returned to Python (zero-copy view via nanobind/eigen).
 */
struct CorrelationMatrix {
    Eigen::MatrixXd values;
};

NB_MODULE(_zinc_risk, module) {
    module.doc() = "zinc::risk — historical VaR, CVaR, drawdown, and correlation kernels";

    nb::class_<CorrelationMatrix>(module, "CorrelationMatrix",
                                  "Pearson correlation matrix of column variables.")
        .def_prop_ro(
            "values", [](const CorrelationMatrix& self) { return nb::cast(self.values); },
            "Correlation coefficients as a C-contiguous float64 matrix (variables × variables).")
        .def_prop_ro(
            "rows", [](const CorrelationMatrix& self) { return self.values.rows(); },
            "Number of variables (rows).")
        .def_prop_ro(
            "cols", [](const CorrelationMatrix& self) { return self.values.cols(); },
            "Number of variables (columns).");

    module.def(
        "historical_var",
        [](const ContiguousVector& samples, double alpha) {
            return zinc::risk::historical_var(as_span(samples), alpha);
        },
        nb::arg("samples"), nb::arg("alpha") = 0.05,
        R"doc(
Historical (non-parametric) lower-tail Value-at-Risk.

Computes the nearest-rank alpha-quantile of samples in ascending order using
std::nth_element (linear average time). For a return series this is the loss
threshold such that at most a fraction alpha of observations lie below it.
)doc");

    module.def(
        "cvar",
        [](const ContiguousVector& samples, double alpha) {
            return zinc::risk::cvar(as_span(samples), alpha);
        },
        nb::arg("samples"), nb::arg("alpha") = 0.05,
        R"doc(
Historical Conditional VaR (Expected Shortfall) in the lower tail.

CVaR is the arithmetic mean of all observations less than or equal to the
historical alpha-quantile (inclusive).
)doc");

    module.def(
        "max_drawdown",
        [](const ContiguousVector& wealth) { return zinc::risk::max_drawdown(as_span(wealth)); },
        nb::arg("wealth"),
        R"doc(
Maximum relative drawdown of a wealth (equity) series.

For each point W_t, relative drawdown is (max_{s <= t} W_s - W_t) / max_{s <= t} W_s.
Returns the maximum over t in [0, 1].
)doc");

    module.def(
        "correlation_matrix",
        [](const ContiguousMatrix& data) {
            if (data.ndim() != 2) {
                throw std::invalid_argument("data must be a two-dimensional array");
            }
            const Eigen::Index rows = static_cast<Eigen::Index>(data.shape(0));
            const Eigen::Index cols = static_cast<Eigen::Index>(data.shape(1));
            Eigen::Map<const Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>>
                mapped(data.data(), rows, cols);
            return CorrelationMatrix{zinc::risk::correlation_matrix(mapped)};
        },
        nb::arg("data"),
        R"doc(
Pearson correlation matrix of column variables.

Each row of data is one observation; each column is one variable. Uses sample
covariance with Bessel correction (n-1 denominator).
)doc");
}
