"""pytest mirrors of cpp/tests/ta_*_test.cpp."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("zinc_native._zinc_ta", reason="C++ kernels not compiled — run make build-cpp")
from zinc_native import ta

PERIOD = 3

REFERENCE_OHLC = np.array(
    [
        [8.5, 10.0, 8.0, 9.0],
        [10.0, 12.0, 9.0, 11.0],
        [9.5, 11.0, 9.0, 10.0],
        [11.0, 13.0, 10.0, 12.0],
        [12.0, 14.0, 11.0, 13.0],
        [11.5, 13.0, 10.0, 12.0],
        [13.0, 15.0, 12.0, 14.0],
        [14.0, 16.0, 13.0, 15.0],
        [13.5, 15.0, 12.0, 14.0],
        [15.0, 17.0, 14.0, 16.0],
    ],
    dtype=np.float64,
)

REFERENCE_CLOSES = np.array(
    [9.0, 11.0, 10.0, 12.0, 13.0, 12.0, 14.0, 15.0, 14.0, 16.0],
    dtype=np.float64,
)


def _regime_accuracy(predicted: np.ndarray, truth: np.ndarray) -> float:
    if predicted.size == 0 or predicted.size != truth.size:
        return 0.0
    direct = float(np.mean(predicted == truth))
    flipped = float(np.mean(predicted == (1 - truth)))
    return max(direct, flipped)


def _make_synthetic_two_regime(length: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    true_states = np.empty(length, dtype=np.int64)
    observations = np.empty(length, dtype=np.float64)
    state = 0
    for index in range(length):
        if index > 0 and rng.random() < 0.05:
            state = 1 - state
        true_states[index] = state
        observations[index] = rng.normal(0.0, 0.3) if state == 0 else rng.normal(3.0, 0.3)
    return observations, true_states


class TestAtr:
    def test_happy_path_pandas_ta_reference_literal(self) -> None:
        values = ta.atr(REFERENCE_OHLC, PERIOD)
        assert len(values) == len(REFERENCE_OHLC)
        assert values[2] == pytest.approx(2.333333333333333, abs=1e-8)
        assert values[5] == pytest.approx(2.802469135802469, abs=1e-8)
        assert values[9] == pytest.approx(2.960981562660121, abs=1e-8)

    def test_empty_and_invalid_period_returns_empty(self) -> None:
        assert ta.atr(np.empty((0, 4)), PERIOD).size == 0
        assert ta.atr(REFERENCE_OHLC, 0).size == 0

    def test_single_bar_period_one_equals_true_range(self) -> None:
        ohlc = np.array([[1.0, 5.0, 0.5, 3.0]])
        values = ta.atr(ohlc, 1)
        assert len(values) == 1
        assert values[0] == pytest.approx(4.5)

    def test_random_bars_produce_positive_finite_atr(self) -> None:
        rng = np.random.default_rng(0xA7C42)
        bars = np.empty((100, 4))
        last_close = rng.uniform(10.0, 100.0)
        for index in range(100):
            close = rng.uniform(10.0, 100.0)
            high = max(close, last_close) + 1.0
            low = min(close, last_close) - 1.0
            bars[index] = [last_close, high, low, close]
            last_close = close

        values = ta.atr(bars, 14)
        for value in values[13:]:
            assert np.isfinite(value)
            assert value > 0.0

    def test_numerical_stability_large_prices(self) -> None:
        ohlc = np.array(
            [
                [1.0e6, 1.01e6, 0.99e6, 1.0e6],
                [1.0e6, 1.02e6, 0.98e6, 1.01e6],
                [1.01e6, 1.03e6, 1.0e6, 1.02e6],
            ]
        )
        values = ta.atr(ohlc, 3)
        assert values[2] == pytest.approx(30000.0, abs=1e-3)


class TestAdx:
    def test_happy_path_pandas_ta_reference_literal(self) -> None:
        values = ta.adx(REFERENCE_OHLC, PERIOD)
        assert len(values) == len(REFERENCE_OHLC)
        assert values[2] == pytest.approx(33.333333333333336, abs=1e-8)
        assert values[5] == pytest.approx(59.070442988005545, abs=1e-8)
        assert values[9] == pytest.approx(55.33901818766078, abs=1e-8)

    def test_empty_and_invalid_period_returns_empty(self) -> None:
        assert ta.adx(np.empty((0, 4)), PERIOD).size == 0
        assert ta.adx(REFERENCE_OHLC, 0).size == 0

    def test_single_bar_returns_nan(self) -> None:
        ohlc = np.array([[1.0, 2.0, 0.5, 1.5]])
        values = ta.adx(ohlc, 3)
        assert len(values) == 1
        assert np.isnan(values[0])

    def test_random_bars_adx_bounded_zero_to_one_hundred(self) -> None:
        rng = np.random.default_rng(0xAD1123)
        bars = np.empty((120, 4))
        last_close = rng.uniform(20.0, 80.0)
        for index in range(120):
            close = rng.uniform(20.0, 80.0)
            high = max(close, last_close) + 0.5
            low = min(close, last_close) - 0.5
            bars[index] = [last_close, high, low, close]
            last_close = close

        values = ta.adx(bars, 14)
        for value in values[27:]:
            if np.isfinite(value):
                assert 0.0 <= value <= 100.0

    def test_numerical_stability_large_prices(self) -> None:
        scaled = REFERENCE_OHLC * 1.0e6
        reference = ta.adx(REFERENCE_OHLC, PERIOD)
        scaled_values = ta.adx(scaled, PERIOD)
        assert len(reference) == len(scaled_values)
        for index in range(2, len(reference)):
            if np.isfinite(reference[index]):
                assert scaled_values[index] == pytest.approx(reference[index], abs=1e-6)


class TestZscore:
    def test_happy_path_pandas_ta_reference_literal(self) -> None:
        values = ta.zscore(REFERENCE_CLOSES, PERIOD)
        assert len(values) == len(REFERENCE_CLOSES)
        assert np.isnan(values[0])
        assert np.isnan(values[1])
        assert values[2] == pytest.approx(0.0)
        assert values[3] == pytest.approx(1.224744871391589, abs=1e-8)
        assert values[9] == pytest.approx(1.224744871391589, abs=1e-8)

    def test_empty_and_invalid_period_returns_empty(self) -> None:
        assert ta.zscore(np.array([]), PERIOD).size == 0
        assert ta.zscore(REFERENCE_CLOSES, 0).size == 0

    def test_single_element_returns_nan(self) -> None:
        values = ta.zscore(np.array([42.0]), 3)
        assert len(values) == 1
        assert np.isnan(values[0])

    def test_constant_window_yields_zero(self) -> None:
        series = np.array([5.0, 5.0, 5.0, 5.0])
        values = ta.zscore(series, 3)
        assert values[2] == pytest.approx(0.0)
        assert values[3] == pytest.approx(0.0)

    def test_numerical_stability_large_magnitude(self) -> None:
        series = np.array([1.0e9, 1.0e9 + 2.0, 1.0e9 + 4.0, 1.0e9 + 6.0])
        values = ta.zscore(series, 3)
        assert values[3] == pytest.approx(1.224744871391589, abs=1e-6)


class TestBollinger:
    def test_happy_path_pandas_ta_reference_literal(self) -> None:
        bands = ta.bollinger(REFERENCE_CLOSES, PERIOD, 2.0)
        assert len(bands.middle) == len(REFERENCE_CLOSES)
        assert bands.middle[2] == pytest.approx(10.0)
        assert bands.middle[9] == pytest.approx(15.0)
        assert bands.upper[2] == pytest.approx(11.632993161855648, abs=1e-8)
        assert bands.lower[2] == pytest.approx(8.367006838144352, abs=1e-8)
        assert bands.upper[9] == pytest.approx(16.632993161855648, abs=1e-8)
        assert bands.lower[9] == pytest.approx(13.367006838144352, abs=1e-8)

    def test_empty_and_invalid_period_returns_empty_bands(self) -> None:
        assert ta.bollinger(np.array([]), PERIOD).middle.size == 0
        assert ta.bollinger(REFERENCE_CLOSES, 0).middle.size == 0
        assert ta.bollinger(REFERENCE_CLOSES, PERIOD, 0.0).middle.size == 0

    def test_single_element_period_one_equals_close(self) -> None:
        bands = ta.bollinger(np.array([7.5]), 1, 2.0)
        assert len(bands.middle) == 1
        assert bands.middle[0] == pytest.approx(7.5)
        assert bands.upper[0] == pytest.approx(7.5)
        assert bands.lower[0] == pytest.approx(7.5)

    def test_random_series_upper_dominates_lower(self) -> None:
        rng = np.random.default_rng(0xBB01)
        series = rng.normal(50.0, 5.0, size=80)
        bands = ta.bollinger(series, 20, 2.0)
        for index in range(19, len(series)):
            assert bands.upper[index] >= bands.middle[index]
            assert bands.lower[index] <= bands.middle[index]

    def test_numerical_stability_large_magnitude(self) -> None:
        series = np.array([1.0e6, 1.2e6, 0.9e6, 1.1e6])
        bands = ta.bollinger(series, 3, 2.0)
        assert bands.middle[3] == pytest.approx(1.1e6, abs=1.0)
        assert bands.upper[3] - bands.middle[3] == pytest.approx(
            bands.middle[3] - bands.lower[3], abs=1.0
        )


class TestHmmRegime:
    def test_happy_path_recovers_synthetic_regimes_above_eighty_five_percent(self) -> None:
        observations, true_states = _make_synthetic_two_regime(500, 42)
        result = ta.hmm_regime(observations, 2, 100)
        assert len(result.states) == len(observations)
        assert _regime_accuracy(np.asarray(result.states), true_states) > 0.85

    def test_empty_and_invalid_input_returns_empty(self) -> None:
        assert ta.hmm_regime(np.array([]), 2).states.size == 0
        assert ta.hmm_regime(np.array([1.0, 2.0]), 2).states.size == 0
        assert ta.hmm_regime(np.array([1.0, 2.0, 3.0]), 3).states.size == 0

    def test_single_regime_cluster_still_returns_states(self) -> None:
        observations = np.array([1.0, 1.1, 0.9, 1.05, 0.95])
        result = ta.hmm_regime(observations, 2, 50)
        assert len(result.states) == len(observations)
        assert np.all((result.states == 0) | (result.states == 1))

    def test_separated_regimes_high_accuracy_on_long_series(self) -> None:
        observations: list[float] = []
        truth: list[int] = []
        for block in range(4):
            state = block % 2
            for index in range(100):
                truth.append(state)
                value = (
                    -2.0 + 0.01 * float(index % 5) if state == 0 else 2.0 + 0.01 * float(index % 5)
                )
                observations.append(value)

        result = ta.hmm_regime(np.asarray(observations), 2, 100)
        assert _regime_accuracy(np.asarray(result.states), np.asarray(truth)) > 0.85

    def test_numerical_stability_shift_invariant(self) -> None:
        base_obs, _ = _make_synthetic_two_regime(300, 99)
        shifted = base_obs + 1.0e6
        base_result = ta.hmm_regime(base_obs, 2, 100)
        shifted_result = ta.hmm_regime(shifted, 2, 100)
        assert len(base_result.states) == len(shifted_result.states)
        assert (
            _regime_accuracy(np.asarray(base_result.states), np.asarray(shifted_result.states))
            > 0.85
        )
