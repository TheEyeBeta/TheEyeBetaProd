/**
 * @file   parquet_dataset.cpp
 * @brief  Parquet loader for zinc::bt::Engine.
 */

#include "detail/parquet_dataset.hpp"

#include <algorithm>
#include <memory>
#include <stdexcept>
#include <unordered_map>
#include <utility>

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <parquet/arrow/reader.h>

namespace zinc::bt::detail {

namespace {

template <typename ArrayType>
std::shared_ptr<ArrayType> column_as(const std::shared_ptr<arrow::Table>& table,
                                     const char* name) {
    const std::shared_ptr<arrow::ChunkedArray> chunked = table->GetColumnByName(name);
    if (chunked == nullptr || chunked->num_chunks() != 1) {
        throw std::runtime_error(std::string("missing or chunked column: ") + name);
    }
    return std::static_pointer_cast<ArrayType>(chunked->chunk(0));
}

}  // namespace

LoadedDataset load_parquet_dataset(const std::filesystem::path& parquet_path,
                                   const std::vector<std::string>& universe,
                                   const std::string& start_date,
                                   const std::string& end_date) {
    LoadedDataset dataset;

    if (universe.empty() || start_date.empty() || end_date.empty() || start_date > end_date ||
        parquet_path.empty()) {
        return dataset;
    }

    std::unordered_set<std::string> universe_set(universe.begin(), universe.end());

    arrow::MemoryPool* pool = arrow::default_memory_pool();
    const arrow::Result<std::shared_ptr<arrow::io::ReadableFile>> input_result =
        arrow::io::ReadableFile::Open(parquet_path.string());
    if (!input_result.ok()) {
        return dataset;
    }
    std::shared_ptr<arrow::io::ReadableFile> input = *input_result;

    arrow::Result<std::unique_ptr<parquet::arrow::FileReader>> reader_result =
        parquet::arrow::OpenFile(input, pool);
    if (!reader_result.ok()) {
        return dataset;
    }
    std::unique_ptr<parquet::arrow::FileReader> reader = std::move(*reader_result);

    std::shared_ptr<arrow::Table> table;
    if (!reader->ReadTable(&table).ok()) {
        return dataset;
    }

    const std::shared_ptr<arrow::StringArray> trade_dates =
        column_as<arrow::StringArray>(table, "trade_date");
    const std::shared_ptr<arrow::StringArray> symbols =
        column_as<arrow::StringArray>(table, "symbol");
    const std::shared_ptr<arrow::DoubleArray> closes =
        column_as<arrow::DoubleArray>(table, "close");
    const std::shared_ptr<arrow::Int64Array> volumes =
        column_as<arrow::Int64Array>(table, "volume");
    const std::shared_ptr<arrow::DoubleArray> atr14_values =
        column_as<arrow::DoubleArray>(table, "atr14");
    const std::shared_ptr<arrow::DoubleArray> adv_values =
        column_as<arrow::DoubleArray>(table, "adv");

    std::unordered_map<std::string, TradingDay> days_by_date;

    for (int64_t row = 0; row < table->num_rows(); ++row) {
        const std::string trade_date = trade_dates->GetString(row);
        if (trade_date < start_date || trade_date > end_date) {
            continue;
        }

        const std::string symbol = symbols->GetString(row);
        if (!universe_set.contains(symbol)) {
            continue;
        }

        TradingDay& day = days_by_date[trade_date];
        if (day.trade_date.empty()) {
            day.trade_date = trade_date;
        }

        day.symbols.push_back(symbol);
        day.close.push_back(closes->Value(row));
        day.volume.push_back(volumes->Value(row));
        day.atr14.push_back(atr14_values->Value(row));
        day.adv.push_back(adv_values->Value(row));
    }

    dataset.days.reserve(days_by_date.size());
    for (auto& entry : days_by_date) {
        dataset.days.push_back(std::move(entry.second));
    }

    std::sort(dataset.days.begin(), dataset.days.end(),
              [](const TradingDay& left, const TradingDay& right) {
                  return left.trade_date < right.trade_date;
              });

    return dataset;
}

}  // namespace zinc::bt::detail
