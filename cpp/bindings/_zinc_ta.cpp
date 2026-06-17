/**
 * @file   _zinc_ta.cpp
 * @brief  nanobind bindings for zinc::ta kernels.
 */

#include "zinc/ta/adx.hpp"
#include "zinc/ta/atr.hpp"
#include "zinc/ta/bar.hpp"
#include "zinc/ta/bollinger.hpp"
#include "zinc/ta/hmm_regime.hpp"
#include "zinc/ta/rsi.hpp"
#include "zinc/ta/snapshot_technicals.hpp"
#include "zinc/ta/zscore.hpp"

#include <cstddef>
#include <span>
#include <stdexcept>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/vector.h>

namespace nb = nanobind;

namespace {

using ContiguousVector = nb::ndarray<const double, nb::ndim<1>, nb::c_contig>;
using ContiguousOhlc = nb::ndarray<const double, nb::ndim<2>, nb::c_contig>;

std::span<const double> as_span(const ContiguousVector& array) {
    if (array.ndim() != 1) {
        throw std::invalid_argument("series must be a one-dimensional array");
    }
    return {array.data(), static_cast<std::size_t>(array.shape(0))};
}

std::vector<zinc::ta::Bar> bars_from_ohlc(const ContiguousOhlc& ohlc) {
    if (ohlc.ndim() != 2) {
        throw std::invalid_argument("ohlc must be a two-dimensional array");
    }
    if (ohlc.shape(1) != 4) {
        throw std::invalid_argument("ohlc must have four columns: open, high, low, close");
    }

    const std::size_t count = static_cast<std::size_t>(ohlc.shape(0));
    std::vector<zinc::ta::Bar> bars(count);
    const double* data = ohlc.data();
    for (std::size_t index = 0; index < count; ++index) {
        const std::size_t offset = index * 4;
        bars[index].open = data[offset];
        bars[index].high = data[offset + 1];
        bars[index].low = data[offset + 2];
        bars[index].close = data[offset + 3];
    }
    return bars;
}

} // namespace

NB_MODULE(_zinc_ta, module) {
    module.doc() = "zinc::ta — ATR, ADX, z-score, Bollinger Bands, and HMM regimes";

    nb::class_<zinc::ta::Bar>(module, "Bar", "Single-period open-high-low-close bar.")
        .def(nb::init<>())
        .def_rw("open", &zinc::ta::Bar::open)
        .def_rw("high", &zinc::ta::Bar::high)
        .def_rw("low", &zinc::ta::Bar::low)
        .def_rw("close", &zinc::ta::Bar::close);

    nb::class_<zinc::ta::BollingerBands>(module, "BollingerBands",
                                         "Bollinger Bands (SMA middle, population-std envelopes).")
        .def_prop_ro(
            "lower", [](const zinc::ta::BollingerBands& bands) { return nb::cast(bands.lower); },
            "Lower band series.")
        .def_prop_ro(
            "middle", [](const zinc::ta::BollingerBands& bands) { return nb::cast(bands.middle); },
            "Middle band (SMA) series.")
        .def_prop_ro(
            "upper", [](const zinc::ta::BollingerBands& bands) { return nb::cast(bands.upper); },
            "Upper band series.");

    nb::class_<zinc::ta::HmmRegimeResult>(module, "HmmRegimeResult",
                                          "Decoded hidden states from a Gaussian HMM.")
        .def_prop_ro(
            "states",
            [](const zinc::ta::HmmRegimeResult& result) { return nb::cast(result.states); },
            "Viterbi state index per observation (0 .. n_states-1).");

    module.def(
        "atr",
        [](const ContiguousOhlc& ohlc, int period) {
            return zinc::ta::atr(bars_from_ohlc(ohlc), period);
        },
        nb::arg("ohlc"), nb::arg("period"),
        R"doc(
Wilder Average True Range over OHLC bars.

True range is max(H-L, |H-C_prev|, |L-C_prev|); ATR applies Wilder RMA with window
period (pandas-ta compatible seeding). ohlc shape is (n, 4) with columns
open, high, low, close.
)doc");

    module.def(
        "adx",
        [](const ContiguousOhlc& ohlc, int period) {
            return zinc::ta::adx(bars_from_ohlc(ohlc), period);
        },
        nb::arg("ohlc"), nb::arg("period"),
        R"doc(
Wilder Average Directional Index (ADX).

Computes +DI, -DI, DX, then smooths DX with Wilder RMA to obtain ADX.
ohlc shape is (n, 4) with columns open, high, low, close.
)doc");

    module.def(
        "zscore",
        [](const ContiguousVector& series, int period) {
            return zinc::ta::zscore(as_span(series), period);
        },
        nb::arg("series"), nb::arg("period"),
        R"doc(
Rolling z-score (x_t - mu_t) / sigma_t over a fixed window.

Uses population standard deviation (ddof=0) in the rolling window, consistent
with pandas-ta rolling z-score behaviour.
)doc");

    module.def(
        "bollinger",
        [](const ContiguousVector& series, int period, double std_dev) {
            return zinc::ta::bollinger(as_span(series), period, std_dev);
        },
        nb::arg("series"), nb::arg("period"), nb::arg("std_dev") = 2.0,
        R"doc(
Bollinger Bands around a rolling simple moving average.

middle_t = SMA_t, upper_t = middle_t + k*sigma_t, lower_t = middle_t - k*sigma_t.
)doc");

    module.def(
        "hmm_regime",
        [](const ContiguousVector& observations, int n_states, int max_iter) {
            return zinc::ta::hmm_regime(as_span(observations), n_states, max_iter);
        },
        nb::arg("observations"), nb::arg("n_states") = 2, nb::arg("max_iter") = 100,
        R"doc(
Fit a Gaussian HMM and decode the most likely regime path.

Uses Baum-Welch (EM) parameter estimation and Viterbi decoding. Currently
supports n_states == 2 only.
)doc");

    module.def(
        "rsi",
        [](const ContiguousOhlc& ohlc, int period) {
            return zinc::ta::rsi(bars_from_ohlc(ohlc), period);
        },
        nb::arg("ohlc"), nb::arg("period"),
        R"doc(
Wilder Relative Strength Index (RSI) using close-to-close deltas.
)doc");

    nb::class_<zinc::ta::TechnicalsLast>(module, "TechnicalsLast",
                                         "Last-bar technical indicators for one symbol.")
        .def_ro("atr14", &zinc::ta::TechnicalsLast::atr14)
        .def_ro("adx14", &zinc::ta::TechnicalsLast::adx14)
        .def_ro("rsi14", &zinc::ta::TechnicalsLast::rsi14)
        .def_ro("zscore20", &zinc::ta::TechnicalsLast::zscore20)
        .def_ro("bb_upper20_2", &zinc::ta::TechnicalsLast::bb_upper20_2)
        .def_ro("bb_lower20_2", &zinc::ta::TechnicalsLast::bb_lower20_2);

    module.def(
        "snapshot_technicals_last",
        [](const nb::list& ohlc_series_list) {
            std::vector<std::vector<zinc::ta::Bar>> owned;
            std::vector<std::span<const zinc::ta::Bar>> spans;
            owned.reserve(ohlc_series_list.size());
            spans.reserve(ohlc_series_list.size());
            for (const nb::handle item : ohlc_series_list) {
                const auto array = nb::cast<ContiguousOhlc>(item);
                owned.push_back(bars_from_ohlc(array));
                spans.push_back(owned.back());
            }
            return zinc::ta::snapshot_technicals_last(spans);
        },
        nb::arg("ohlc_series"),
        R"doc(
Compute last-bar technical indicators for many instruments in C++.

Each element of ``ohlc_series`` is an OHLC array with shape (bars, 4).
)doc");
}
