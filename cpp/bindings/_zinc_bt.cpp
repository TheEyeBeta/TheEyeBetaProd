/**
 * @file   _zinc_bt.cpp
 * @brief  nanobind bindings for zinc::bt kernels.
 */

#include "zinc/bt/decision.hpp"
#include "zinc/bt/engine.hpp"
#include "zinc/bt/result.hpp"
#include "zinc/bt/slippage_model.hpp"
#include "zinc/bt/snapshot.hpp"

#include <cstdint>
#include <filesystem>
#include <utility>

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

namespace nb = nanobind;

namespace {

void engine_set_strategy(zinc::bt::Engine& engine, const nb::callable& strategy) {
    engine.set_strategy([strategy](const zinc::bt::Snapshot& snapshot) {
        nb::gil_scoped_acquire acquire;
        return nb::cast<zinc::bt::Decision>(strategy(snapshot));
    });
}

zinc::bt::SlippageModel make_slippage_model(const nb::object& formula) {
    if (formula.is_none()) {
        return zinc::bt::SlippageModel{};
    }
    const nb::callable callable = nb::borrow<nb::callable>(formula);
    return zinc::bt::SlippageModel([callable](const double atr, const double participation) {
        nb::gil_scoped_acquire acquire;
        return nb::cast<double>(callable(atr, participation));
    });
}

} // namespace

NB_MODULE(_zinc_bt, module) {
    module.doc() = "zinc::bt — event-loop backtest engine over daily Parquet data";

    nb::enum_<zinc::bt::Side>(module, "Side", "Side of a simulated fill.")
        .value("Buy", zinc::bt::Side::kBuy)
        .value("Sell", zinc::bt::Side::kSell);

    nb::class_<zinc::bt::Decision>(module, "Decision",
                                   "Target portfolio weight for one instrument on a trading day.")
        .def(nb::init<>())
        .def_rw("symbol_index", &zinc::bt::Decision::symbol_index,
                "Index into the day's Snapshot symbol ordering (0-based).")
        .def_rw("target_weight", &zinc::bt::Decision::target_weight,
                "Desired long-only portfolio weight in [0, 1].");

    nb::class_<zinc::bt::Snapshot>(module, "Snapshot",
                                   "One trading day's cross-section for the configured universe.")
        .def_ro("trade_date", &zinc::bt::Snapshot::trade_date, "ISO date YYYY-MM-DD for this tick.")
        .def_ro("day_index", &zinc::bt::Snapshot::day_index,
                "Zero-based index of this day in the backtest calendar.")
        .def_ro("symbol_names", &zinc::bt::Snapshot::symbol_names,
                "Symbols aligned with the numeric arrays.")
        .def_prop_ro(
            "close",
            [](const zinc::bt::Snapshot& snapshot) {
                return nb::ndarray<const double, nb::numpy>(snapshot.close.data(),
                                                            {snapshot.close.size()});
            },
            "Unadjusted closing prices (C-contiguous float64).")
        .def_prop_ro(
            "atr14",
            [](const zinc::bt::Snapshot& snapshot) {
                return nb::ndarray<const double, nb::numpy>(snapshot.atr14.data(),
                                                            {snapshot.atr14.size()});
            },
            "14-period ATR used for slippage.")
        .def_prop_ro(
            "adv",
            [](const zinc::bt::Snapshot& snapshot) {
                return nb::ndarray<const double, nb::numpy>(snapshot.adv.data(),
                                                            {snapshot.adv.size()});
            },
            "Average daily volume in shares for participation.")
        .def_prop_ro(
            "volume",
            [](const zinc::bt::Snapshot& snapshot) {
                return nb::ndarray<const std::int64_t, nb::numpy>(snapshot.volume.data(),
                                                                  {snapshot.volume.size()});
            },
            "Share volume on the trade date.");

    nb::class_<zinc::bt::Execution>(module, "Execution", "One simulated execution at the close.")
        .def_ro("trade_date", &zinc::bt::Execution::trade_date)
        .def_ro("symbol", &zinc::bt::Execution::symbol)
        .def_ro("side", &zinc::bt::Execution::side)
        .def_ro("quantity", &zinc::bt::Execution::quantity)
        .def_ro("price", &zinc::bt::Execution::price)
        .def_ro("slippage_bps", &zinc::bt::Execution::slippage_bps)
        .def_ro("notional", &zinc::bt::Execution::notional);

    nb::class_<zinc::bt::Metrics>(module, "Metrics", "Summary statistics for a completed run.")
        .def_ro("total_return", &zinc::bt::Metrics::total_return,
                "Cumulative return over the run (final / initial equity - 1).")
        .def_ro("sharpe_ratio", &zinc::bt::Metrics::sharpe_ratio,
                "Annualised Sharpe ratio from daily PnL (252-day scale).")
        .def_ro("max_drawdown", &zinc::bt::Metrics::max_drawdown,
                "Maximum peak-to-trough drawdown fraction.")
        .def_ro("turnover", &zinc::bt::Metrics::turnover,
                "Turnover as traded notional divided by average equity.");

    nb::class_<zinc::bt::Result>(module, "Result", "Full backtest output.")
        .def_prop_ro(
            "daily_pnl", [](const zinc::bt::Result& result) { return nb::cast(result.daily_pnl); },
            "Mark-to-market PnL per calendar day.")
        .def_prop_ro(
            "drawdown_series",
            [](const zinc::bt::Result& result) { return nb::cast(result.drawdown_series); },
            "Running drawdown fraction from the equity peak.")
        .def_prop_ro(
            "executions",
            [](const zinc::bt::Result& result) { return nb::cast(result.executions); },
            "Simulated fills in event-loop order.")
        .def_ro("metrics", &zinc::bt::Result::metrics, "Aggregated performance metrics.");

    nb::class_<zinc::bt::SlippageModel>(
        module, "SlippageModel",
        "Slippage as a function of ATR and participation (trade_size / ADV).")
        .def(
            "__init__",
            [](zinc::bt::SlippageModel* self, nb::object formula) {
                new (self) zinc::bt::SlippageModel(make_slippage_model(formula));
            },
            nb::arg("formula") = nb::none(),
            "Construct a model with an optional custom formula(atr, participation).");

    nb::class_<zinc::bt::Engine>(module, "Engine",
                                 "Daily event-loop backtest engine over daily Parquet market data.")
        .def(nb::init<std::string, std::string, std::string, std::vector<std::string>,
                      zinc::bt::SlippageModel>(),
             nb::arg("strategy_id"), nb::arg("start_date"), nb::arg("end_date"),
             nb::arg("universe"), nb::arg("slippage_model"),
             "Construct an engine for one strategy and calendar window.")
        .def(
            "set_parquet_path",
            [](zinc::bt::Engine& engine, const std::string& path) {
                engine.set_parquet_path(std::filesystem::path(path));
            },
            nb::arg("parquet_path"),
            "Path to the daily Parquet file (trade_date, symbol, OHLCV, atr14, adv).")
        .def("set_strategy", &engine_set_strategy, nb::arg("strategy"),
             "Register the strategy callback invoked once per trading day.")
        .def("run", &zinc::bt::Engine::run, "Run the event loop and produce a backtest result.");
}
