/**
 * @file   decision.hpp
 * @brief  Strategy decision emitted each event-loop tick.
 */

#pragma once

namespace zinc::bt {

/**
 * @brief Target portfolio weight for one instrument on a trading day.
 */
struct Decision {
    /** @brief Index into the day's Snapshot symbol ordering (0-based). */
    int symbol_index = 0;

    /**
     * @brief Desired long-only portfolio weight in @f$[0, 1]@f$ for that symbol.
     *
     * The engine scales the remaining capital to this weight at the close.
     */
    double target_weight = 0.0;
};

}  // namespace zinc::bt
