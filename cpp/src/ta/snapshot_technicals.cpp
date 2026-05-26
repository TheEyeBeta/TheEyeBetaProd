/**
 * @file   snapshot_technicals.cpp
 * @brief  Batch snapshot technical indicator extraction.
 */

#include "zinc/ta/snapshot_technicals.hpp"

#include <cmath>
#include <cstddef>
#include <limits>
#include <vector>

#include "zinc/ta/adx.hpp"
#include "zinc/ta/atr.hpp"
#include "zinc/ta/bollinger.hpp"
#include "zinc/ta/rsi.hpp"
#include "zinc/ta/zscore.hpp"

namespace zinc::ta {

namespace {

double last_finite(const std::vector<double>& series) {
    for (auto iterator = series.rbegin(); iterator != series.rend(); ++iterator) {
        if (std::isfinite(*iterator)) {
            return *iterator;
        }
    }
    return std::numeric_limits<double>::quiet_NaN();
}

std::vector<double> closes_from_bars(std::span<const Bar> bars) {
    std::vector<double> closes(bars.size());
    for (std::size_t index = 0; index < bars.size(); ++index) {
        closes[index] = bars[index].close;
    }
    return closes;
}

}  // namespace

std::vector<TechnicalsLast> snapshot_technicals_last(
    std::span<const std::span<const Bar>> ohlc_by_instrument) {
    std::vector<TechnicalsLast> results(ohlc_by_instrument.size());
    for (std::size_t index = 0; index < ohlc_by_instrument.size(); ++index) {
        const auto bars = ohlc_by_instrument[index];
        if (bars.empty()) {
            continue;
        }
        TechnicalsLast values;
        values.atr14 = last_finite(atr(bars, 14));
        values.adx14 = last_finite(adx(bars, 14));
        values.rsi14 = last_finite(rsi(bars, 14));
        const auto closes = closes_from_bars(bars);
        values.zscore20 = last_finite(zscore(closes, 20));
        const auto bands = bollinger(closes, 20, 2.0);
        values.bb_upper20_2 = last_finite(bands.upper);
        values.bb_lower20_2 = last_finite(bands.lower);
        results[index] = values;
    }
    return results;
}

}  // namespace zinc::ta
