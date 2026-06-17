/**
 * @file   ta_test_reference.hpp
 * @brief  Shared OHLC fixtures and pandas-ta reference literals for TA tests.
 */

#pragma once

#include "zinc/ta/bar.hpp"

#include <vector>

namespace zinc::ta_test {

inline std::vector<zinc::ta::Bar> reference_bars() {
    return {
        {8.5, 10.0, 8.0, 9.0},    {10.0, 12.0, 9.0, 11.0},  {9.5, 11.0, 9.0, 10.0},
        {11.0, 13.0, 10.0, 12.0}, {12.0, 14.0, 11.0, 13.0}, {11.5, 13.0, 10.0, 12.0},
        {13.0, 15.0, 12.0, 14.0}, {14.0, 16.0, 13.0, 15.0}, {13.5, 15.0, 12.0, 14.0},
        {15.0, 17.0, 14.0, 16.0},
    };
}

inline std::vector<double> reference_closes() {
    return {9.0, 11.0, 10.0, 12.0, 13.0, 12.0, 14.0, 15.0, 14.0, 16.0};
}

} // namespace zinc::ta_test
