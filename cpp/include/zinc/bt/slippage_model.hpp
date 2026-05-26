/**
 * @file   slippage_model.hpp
 * @brief  Slippage as a function of ATR and participation (trade_size / ADV).
 */

#pragma once

#include <functional>

namespace zinc::bt {

/**
 * @brief Slippage model @f$s = f(\mathrm{ATR}, \mathrm{trade\_size} / \mathrm{ADV})@f$.
 *
 * The callable returns a **fractional** price impact (e.g. @c 0.0001 = 1 bp).
 */
class SlippageModel {
  public:
    using Formula = std::function<double(double atr, double participation)>;

    /**
     * @brief Construct a model with an optional custom formula.
     *
     * @param formula Callable returning slippage fraction; defaults to
     *        @f$\min(0.01,\; 10^{-4} \cdot \mathrm{ATR} \cdot \mathrm{participation})@f$.
     */
    explicit SlippageModel(Formula formula = {});

    /**
     * @brief Compute slippage fraction for a trade.
     *
     * @param atr          Average true range of the instrument.
     * @param trade_size   Absolute share quantity traded.
     * @param adv          Average daily volume in shares (&gt; 0).
     *
     * @return Non-negative slippage fraction applied against the close.
     */
    [[nodiscard]] double slippage_fraction(double atr, double trade_size, double adv) const noexcept;

  private:
    Formula formula_;
};

}  // namespace zinc::bt
