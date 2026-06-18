/**
 * @file   slippage_model.cpp
 * @brief  Slippage model implementation.
 */

#include "zinc/bt/slippage_model.hpp"

#include <algorithm>
#include <cmath>

namespace zinc::bt {

namespace {

double default_formula(const double atr, const double participation) noexcept {
    return std::min(0.01, 1.0e-4 * std::max(atr, 0.0) * std::max(participation, 0.0));
}

} // namespace

SlippageModel::SlippageModel(Formula formula) : formula_(std::move(formula)) {
    if (!formula_) {
        formula_ = default_formula;
    }
}

double SlippageModel::slippage_fraction(const double atr, const double trade_size,
                                        const double adv) const noexcept {
    const double participation = std::abs(trade_size) / std::max(adv, 1.0);
    return std::max(0.0, formula_(atr, participation));
}

} // namespace zinc::bt
