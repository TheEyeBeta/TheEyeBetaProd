/**
 * @file   result.hpp
 * @brief  Backtest output aggregates returned by the engine.
 */

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace zinc::bt {

/**
 * @brief Side of a simulated fill.
 */
enum class Side { kBuy, kSell };

/**
 * @brief One simulated execution at the close.
 */
struct Execution {
    std::string trade_date;
    std::string symbol;
    Side side = Side::kBuy;
    double quantity = 0.0;
    double price = 0.0;
    double slippage_bps = 0.0;
    double notional = 0.0;
};

/**
 * @brief Summary statistics for a completed run.
 */
struct Metrics {
    /** @brief Cumulative return over the run (final / initial equity - 1). */
    double total_return = 0.0;

    /** @brief Annualised Sharpe ratio from daily PnL (252-day scale). */
    double sharpe_ratio = 0.0;

    /** @brief Maximum peak-to-trough drawdown fraction. */
    double max_drawdown = 0.0;

    /** @brief Turnover as traded notional divided by average equity. */
    double turnover = 0.0;
};

/**
 * @brief Full backtest output.
 */
struct Result {
    /** @brief Mark-to-market PnL per calendar day (length = trading days). */
    std::vector<double> daily_pnl;

    /** @brief Running drawdown fraction from the equity peak. */
    std::vector<double> drawdown_series;

    /** @brief Simulated fills in event-loop order. */
    std::vector<Execution> executions;

    /** @brief Aggregated performance metrics. */
    Metrics metrics;
};

} // namespace zinc::bt
