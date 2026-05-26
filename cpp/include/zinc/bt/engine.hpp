/**
 * @file   engine.hpp
 * @brief  Event-loop backtest engine over daily Parquet market data.
 */

#pragma once

#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#include "zinc/bt/decision.hpp"
#include "zinc/bt/result.hpp"
#include "zinc/bt/slippage_model.hpp"
#include "zinc/bt/snapshot.hpp"

namespace zinc::bt {

/**
 * @brief Daily event-loop backtest engine.
 *
 * Loads a unified daily Parquet dataset via Arrow (column buffers, no Python bridge),
 * walks the calendar between @p start_date and @p end_date, invokes the registered
 * strategy callback each day, applies the slippage model to fills, and returns
 * PnL, drawdown, executions, and summary metrics.
 */
class Engine {
  public:
    using Strategy = std::function<Decision(const Snapshot&)>;

    /**
     * @brief Construct an engine for one strategy and calendar window.
     *
     * @param strategy_id    Identifier stored for logging (not used in simulation).
     * @param start_date     Inclusive ISO start date @c YYYY-MM-DD.
     * @param end_date       Inclusive ISO end date @c YYYY-MM-DD.
     * @param universe       Symbols to trade (must exist in the Parquet dataset).
     * @param slippage_model Model used for close auction fills.
     *
     * @pre @p start_date &lt;= @p end_date lexicographically when both non-empty.
     */
    Engine(std::string strategy_id, std::string start_date, std::string end_date,
           std::vector<std::string> universe, SlippageModel slippage_model);

    /**
     * @brief Path to the daily Parquet file (columns: trade_date, symbol, open, high,
     *        low, close, volume, atr14, adv).
     *
     * @param parquet_path Filesystem path readable by Arrow Parquet.
     */
    void set_parquet_path(const std::filesystem::path& parquet_path);

    /**
     * @brief Register the strategy callback invoked once per trading day.
     *
     * @param strategy Callable returning the desired target weight for the day.
     */
    void set_strategy(Strategy strategy);

    /**
     * @brief Run the event loop and produce a backtest result.
     *
     * @return Result with daily PnL, drawdown series, fills, and metrics. Empty when
     *         data, universe, or strategy are missing/invalid.
     *
     * @pre @ref set_parquet_path and @ref set_strategy were called successfully.
     *
     * @example
     * @code
     * zinc::bt::Engine engine("buy_hold", "2024-01-01", "2024-04-09", {"SPY"},
     *                         zinc::bt::SlippageModel{});
     * engine.set_parquet_path("/data/daily.parquet");
     * engine.set_strategy([](const zinc::bt::Snapshot& day) {
     *     return zinc::bt::Decision{.symbol_index = 0, .target_weight = 1.0};
     * });
     * const auto result = engine.run();
     * @endcode
     */
    [[nodiscard]] Result run();

  private:
    std::string strategy_id_;
    std::string start_date_;
    std::string end_date_;
    std::vector<std::string> universe_;
    SlippageModel slippage_model_;
    std::filesystem::path parquet_path_;
    Strategy strategy_;
};

}  // namespace zinc::bt
