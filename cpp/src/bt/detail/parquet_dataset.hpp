/**
 * @file   parquet_dataset.hpp
 * @brief  Internal Parquet loader for zinc::bt::Engine.
 */

#pragma once

#include <filesystem>
#include <string>
#include <unordered_set>
#include <vector>

namespace zinc::bt::detail {

/**
 * @brief One trading day's bars for all active universe symbols.
 */
struct TradingDay {
    std::string trade_date;
    std::vector<std::string> symbols;
    std::vector<double> close;
    std::vector<double> atr14;
    std::vector<double> adv;
    std::vector<int64_t> volume;
};

/**
 * @brief Calendar-ordered dataset filtered to universe and date window.
 */
struct LoadedDataset {
    std::vector<TradingDay> days;
};

/**
 * @brief Load and group a daily Parquet file via Arrow column buffers.
 *
 * Expected columns: trade_date, symbol, open, high, low, close, volume, atr14, adv.
 */
[[nodiscard]] LoadedDataset load_parquet_dataset(const std::filesystem::path& parquet_path,
                                                 const std::vector<std::string>& universe,
                                                 const std::string& start_date,
                                                 const std::string& end_date);

}  // namespace zinc::bt::detail
