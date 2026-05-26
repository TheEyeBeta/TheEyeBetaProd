/**
 * @file   bar.hpp
 * @brief  OHLC bar for technical-analysis kernels.
 */

#pragma once

namespace zinc::ta {

/**
 * @brief Single-period open-high-low-close bar.
 */
struct Bar {
    double open = 0.0;
    double high = 0.0;
    double low = 0.0;
    double close = 0.0;
};

}  // namespace zinc::ta
