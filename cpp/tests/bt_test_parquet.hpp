/**
 * @file   bt_test_parquet.hpp
 * @brief  Test helper to write daily Parquet fixtures for zinc::bt::Engine.
 */

#pragma once

#include <filesystem>
#include <memory>
#include <string>
#include <vector>

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <parquet/arrow/writer.h>

namespace zinc::bt::test {

/**
 * @brief One row of the canonical daily market dataset schema.
 */
struct DailyMarketRow {
    std::string trade_date;
    std::string symbol;
    double open = 0.0;
    double high = 0.0;
    double low = 0.0;
    double close = 0.0;
    int64_t volume = 0;
    double atr14 = 0.0;
    double adv = 0.0;
};

/**
 * @brief Write rows to a Parquet file using Arrow column builders.
 */
inline bool write_daily_parquet(const std::filesystem::path& path,
                                const std::vector<DailyMarketRow>& rows) {
    arrow::StringBuilder trade_date_builder;
    arrow::StringBuilder symbol_builder;
    arrow::DoubleBuilder open_builder;
    arrow::DoubleBuilder high_builder;
    arrow::DoubleBuilder low_builder;
    arrow::DoubleBuilder close_builder;
    arrow::Int64Builder volume_builder;
    arrow::DoubleBuilder atr14_builder;
    arrow::DoubleBuilder adv_builder;

    for (const DailyMarketRow& row : rows) {
        if (!trade_date_builder.Append(row.trade_date).ok() ||
            !symbol_builder.Append(row.symbol).ok() || !open_builder.Append(row.open).ok() ||
            !high_builder.Append(row.high).ok() || !low_builder.Append(row.low).ok() ||
            !close_builder.Append(row.close).ok() || !volume_builder.Append(row.volume).ok() ||
            !atr14_builder.Append(row.atr14).ok() || !adv_builder.Append(row.adv).ok()) {
            return false;
        }
    }

    const arrow::Result<std::shared_ptr<arrow::Array>> trade_date_result =
        trade_date_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> symbol_result = symbol_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> open_result = open_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> high_result = high_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> low_result = low_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> close_result = close_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> volume_result = volume_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> atr14_result = atr14_builder.Finish();
    const arrow::Result<std::shared_ptr<arrow::Array>> adv_result = adv_builder.Finish();
    if (!trade_date_result.ok() || !symbol_result.ok() || !open_result.ok() || !high_result.ok() ||
        !low_result.ok() || !close_result.ok() || !volume_result.ok() || !atr14_result.ok() ||
        !adv_result.ok()) {
        return false;
    }

    const std::shared_ptr<arrow::Array> trade_date_array = *trade_date_result;
    const std::shared_ptr<arrow::Array> symbol_array = *symbol_result;
    const std::shared_ptr<arrow::Array> open_array = *open_result;
    const std::shared_ptr<arrow::Array> high_array = *high_result;
    const std::shared_ptr<arrow::Array> low_array = *low_result;
    const std::shared_ptr<arrow::Array> close_array = *close_result;
    const std::shared_ptr<arrow::Array> volume_array = *volume_result;
    const std::shared_ptr<arrow::Array> atr14_array = *atr14_result;
    const std::shared_ptr<arrow::Array> adv_array = *adv_result;

    const std::shared_ptr<arrow::Schema> schema = arrow::schema(
        {arrow::field("trade_date", arrow::utf8()), arrow::field("symbol", arrow::utf8()),
         arrow::field("open", arrow::float64()), arrow::field("high", arrow::float64()),
         arrow::field("low", arrow::float64()), arrow::field("close", arrow::float64()),
         arrow::field("volume", arrow::int64()), arrow::field("atr14", arrow::float64()),
         arrow::field("adv", arrow::float64())});

    const std::shared_ptr<arrow::Table> table =
        arrow::Table::Make(schema, {trade_date_array, symbol_array, open_array, high_array,
                                    low_array, close_array, volume_array, atr14_array, adv_array});

    const arrow::Result<std::shared_ptr<arrow::io::FileOutputStream>> output_result =
        arrow::io::FileOutputStream::Open(path.string());
    if (!output_result.ok()) {
        return false;
    }

    return parquet::arrow::WriteTable(*table, arrow::default_memory_pool(), *output_result,
                                      static_cast<int64_t>(rows.size()))
        .ok();
}

} // namespace zinc::bt::test
