/**
 * @file   engine.cpp
 * @brief  Event-loop backtest engine implementation.
 */

#include "zinc/bt/engine.hpp"

#include "detail/parquet_dataset.hpp"
#include "zinc/risk/max_drawdown.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <unordered_map>
#include <utility>

namespace zinc::bt {

namespace {

constexpr double kInitialEquity = 1.0;

double clamp_weight(const double weight) noexcept {
    return std::clamp(weight, 0.0, 1.0);
}

Snapshot make_snapshot(const detail::TradingDay& day, const int day_index) {
    Snapshot snapshot;
    snapshot.trade_date = day.trade_date;
    snapshot.day_index = day_index;
    snapshot.symbol_names = day.symbols;
    snapshot.close = day.close;
    snapshot.atr14 = day.atr14;
    snapshot.adv = day.adv;
    snapshot.volume = day.volume;
    return snapshot;
}

Metrics compute_metrics(const std::vector<double>& daily_pnl,
                        const std::vector<double>& equity_curve,
                        const std::vector<Execution>& executions) {
    Metrics metrics;
    if (equity_curve.empty()) {
        return metrics;
    }

    metrics.total_return = equity_curve.back() / kInitialEquity - 1.0;

    if (daily_pnl.size() >= 2) {
        const double mean_pnl = std::accumulate(daily_pnl.begin(), daily_pnl.end(), 0.0) /
                                static_cast<double>(daily_pnl.size());
        double variance = 0.0;
        for (const double pnl : daily_pnl) {
            const double delta = pnl - mean_pnl;
            variance += delta * delta;
        }
        variance /= static_cast<double>(daily_pnl.size() - 1);
        const double std_dev = std::sqrt(std::max(variance, 0.0));
        if (std_dev > 0.0) {
            metrics.sharpe_ratio = (mean_pnl / std_dev) * std::sqrt(252.0);
        }
    }

    metrics.max_drawdown = zinc::risk::max_drawdown(equity_curve);

    const double average_equity = std::accumulate(equity_curve.begin(), equity_curve.end(), 0.0) /
                                  static_cast<double>(equity_curve.size());
    double traded_notional = 0.0;
    for (const Execution& execution : executions) {
        traded_notional += std::abs(execution.notional);
    }
    if (average_equity > 0.0) {
        metrics.turnover = traded_notional / average_equity;
    }

    return metrics;
}

} // namespace

Engine::Engine(std::string strategy_id, std::string start_date, std::string end_date,
               std::vector<std::string> universe, SlippageModel slippage_model)
    : strategy_id_(std::move(strategy_id)), start_date_(std::move(start_date)),
      end_date_(std::move(end_date)), universe_(std::move(universe)),
      slippage_model_(std::move(slippage_model)) {}

void Engine::set_parquet_path(const std::filesystem::path& parquet_path) {
    parquet_path_ = parquet_path;
}

void Engine::set_strategy(Strategy strategy) {
    strategy_ = std::move(strategy);
}

Result Engine::run() {
    (void)strategy_id_;
    Result result;
    if (!strategy_ || universe_.empty() || parquet_path_.empty() || start_date_.empty() ||
        end_date_.empty() || start_date_ > end_date_) {
        return result;
    }

    const detail::LoadedDataset dataset =
        detail::load_parquet_dataset(parquet_path_, universe_, start_date_, end_date_);
    if (dataset.days.empty()) {
        return result;
    }

    std::unordered_map<std::string, double> shares_by_symbol;
    double cash = kInitialEquity;
    double previous_equity = kInitialEquity;
    double peak_equity = kInitialEquity;

    std::vector<double> equity_curve;
    equity_curve.reserve(dataset.days.size());

    for (std::size_t day_index = 0; day_index < dataset.days.size(); ++day_index) {
        const detail::TradingDay& day = dataset.days[day_index];
        const Snapshot snapshot = make_snapshot(day, static_cast<int>(day_index));
        const Decision decision = strategy_(snapshot);

        if (day.symbols.empty()) {
            continue;
        }

        int symbol_index_value = decision.symbol_index;
        if (symbol_index_value < 0 ||
            static_cast<std::size_t>(symbol_index_value) >= day.symbols.size()) {
            symbol_index_value = 0;
        }

        const std::size_t symbol_index = static_cast<std::size_t>(symbol_index_value);
        const std::string& symbol = day.symbols[symbol_index];
        const double close = day.close[symbol_index];
        const double atr = day.atr14[symbol_index];
        const double adv = day.adv[symbol_index];

        if (!(close > 0.0)) {
            continue;
        }

        double shares = shares_by_symbol[symbol];
        const double pre_trade_equity = cash + shares * close;
        const double target_weight = clamp_weight(decision.target_weight);
        const double target_value = pre_trade_equity * target_weight;
        const double current_value = shares * close;
        const double trade_value = target_value - current_value;

        if (std::abs(trade_value) > 1e-12) {
            const double trade_shares = trade_value / close;
            const double slippage = slippage_model_.slippage_fraction(atr, trade_shares, adv);
            const bool is_buy = trade_shares > 0.0;
            const double execution_price = close * (is_buy ? (1.0 + slippage) : (1.0 - slippage));

            cash -= trade_shares * execution_price;
            shares += trade_shares;
            shares_by_symbol[symbol] = shares;

            Execution execution;
            execution.trade_date = day.trade_date;
            execution.symbol = symbol;
            execution.side = is_buy ? Side::kBuy : Side::kSell;
            execution.quantity = std::abs(trade_shares);
            execution.price = execution_price;
            execution.slippage_bps = slippage * 10000.0;
            execution.notional = std::abs(trade_shares * execution_price);
            result.executions.push_back(std::move(execution));
        }

        const double equity = cash + shares * close;
        equity_curve.push_back(equity);
        result.daily_pnl.push_back(equity - previous_equity);
        previous_equity = equity;

        peak_equity = std::max(peak_equity, equity);
        const double drawdown = peak_equity > 0.0 ? (peak_equity - equity) / peak_equity : 0.0;
        result.drawdown_series.push_back(drawdown);
    }

    result.metrics = compute_metrics(result.daily_pnl, equity_curve, result.executions);
    return result;
}

} // namespace zinc::bt
