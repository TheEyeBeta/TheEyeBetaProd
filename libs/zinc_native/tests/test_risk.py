"""pytest mirrors of cpp/tests/risk_*_test.cpp."""

from __future__ import annotations

import sys as _sys

import numpy as np
import pytest

_zinc_risk = _sys.modules.get("zinc_native._zinc_risk")
if _zinc_risk is None:
    pytest.importorskip(
        "zinc_native._zinc_risk", reason="C++ kernels not compiled — run make build-cpp"
    )
elif not getattr(_zinc_risk, "__file__", None):
    pytest.skip(
        "C++ kernels not compiled — zinc_native.risk is a Python stub", allow_module_level=True
    )
from zinc_native import risk

PHI_INV_005 = -1.6448536269514102


class TestHistoricalVar:
    def test_happy_path_hand_computed(self) -> None:
        samples = np.array([-5.0, -3.0, -2.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        assert risk.historical_var(samples, 0.20) == -3.0

    def test_empty_input_returns_nan(self) -> None:
        assert np.isnan(risk.historical_var(np.array([]), 0.05))
        assert np.isnan(risk.historical_var(np.array([1.0]), 0.0))
        assert np.isnan(risk.historical_var(np.array([1.0]), 1.0))

    def test_single_element_returns_that_value(self) -> None:
        sample = np.array([0.42])
        assert risk.historical_var(sample, 0.05) == pytest.approx(0.42)

    def test_normal_tail_matches_inverse_phi_within_two_percent(self) -> None:
        rng = np.random.default_rng(0xC0FFEE42)
        samples = rng.normal(0.0, 1.0, size=50_000)
        var = risk.historical_var(samples, 0.05)
        relative_error = abs((var - PHI_INV_005) / PHI_INV_005)
        assert relative_error < 0.02

    def test_numerical_stability_against_reference_literal(self) -> None:
        samples = np.array([3.0, -1.0, 2.0, -2.0, 0.0, 1.0, -3.0, 4.0])
        assert risk.historical_var(samples, 0.25) == -2.0


class TestCvar:
    def test_happy_path_hand_computed(self) -> None:
        samples = np.array([-5.0, -3.0, -2.0, 0.0, 1.0])
        expected = (-5.0 + -3.0) / 2.0
        assert risk.cvar(samples, 0.40) == pytest.approx(expected)

    def test_empty_input_returns_nan(self) -> None:
        assert np.isnan(risk.cvar(np.array([]), 0.05))
        assert np.isnan(risk.cvar(np.array([1.0]), -0.1))
        assert np.isnan(risk.cvar(np.array([1.0]), 1.0))

    def test_single_element_returns_that_value(self) -> None:
        sample = np.array([-1.25])
        assert risk.cvar(sample, 0.10) == pytest.approx(-1.25)

    def test_tail_mean_not_above_var_for_random_data(self) -> None:
        rng = np.random.default_rng(0xDEADBEEF)
        samples = rng.uniform(-2.0, 2.0, size=2_000)
        alpha = 0.10
        var = risk.historical_var(samples, alpha)
        es = risk.cvar(samples, alpha)
        assert es <= var + 1e-12

    def test_numerical_stability_against_reference_literal(self) -> None:
        samples = np.array([-5.0, -3.0, -2.0, 0.0, 1.0, 2.0])
        assert risk.cvar(samples, 0.50) == pytest.approx(-3.3333333333333335)


class TestMaxDrawdown:
    def test_happy_path_hand_computed(self) -> None:
        wealth = np.array([100.0, 120.0, 90.0, 110.0])
        assert risk.max_drawdown(wealth) == pytest.approx(0.25)

    def test_empty_and_invalid_input_returns_nan(self) -> None:
        assert np.isnan(risk.max_drawdown(np.array([])))
        assert np.isnan(risk.max_drawdown(np.array([100.0, 0.0, 50.0])))

    def test_single_element_returns_zero(self) -> None:
        wealth = np.array([50.0])
        assert risk.max_drawdown(wealth) == 0.0

    def test_random_walk_drawdown_bounded(self) -> None:
        rng = np.random.default_rng(0xA11CE)
        wealth = np.empty(500)
        wealth[0] = 100.0
        for index in range(1, wealth.size):
            wealth[index] = wealth[index - 1] * rng.lognormal(0.0, 0.05)
        drawdown = risk.max_drawdown(wealth)
        assert 0.0 <= drawdown <= 1.0

    def test_numerical_stability_against_reference_literal(self) -> None:
        wealth = np.array([1.0e6, 1.2e6, 9.0e5, 1.1e6])
        assert risk.max_drawdown(wealth) == pytest.approx(0.25)


class TestCorrelationMatrix:
    def test_happy_path_hand_computed_perfect_correlation(self) -> None:
        data = np.array([[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]])
        result = risk.correlation_matrix(data)
        corr = result.values
        assert corr.shape == (2, 2)
        assert corr[0, 0] == pytest.approx(1.0)
        assert corr[1, 1] == pytest.approx(1.0)
        assert corr[0, 1] == pytest.approx(1.0)
        assert corr[1, 0] == pytest.approx(1.0)
        assert result.rows == 2
        assert result.cols == 2

    def test_empty_and_degenerate_input(self) -> None:
        empty = np.empty((0, 2))
        empty_corr = risk.correlation_matrix(empty).values
        assert empty_corr.shape == (2, 2)
        assert np.isnan(empty_corr[0, 1])

        single_row = np.array([[1.0, 2.0]])
        single_corr = risk.correlation_matrix(single_row).values
        assert single_corr[0, 0] == pytest.approx(1.0)
        assert np.isnan(single_corr[0, 1])

    def test_single_column_identity(self) -> None:
        data = np.array([[1.0], [2.0], [3.0], [4.0]])
        corr = risk.correlation_matrix(data).values
        assert corr.shape == (1, 1)
        assert corr[0, 0] == pytest.approx(1.0)

    def test_random_matrix_is_symmetric_with_unit_diagonal(self) -> None:
        rng = np.random.default_rng(0x5151)
        data = rng.normal(0.0, 1.0, size=(200, 4))
        corr = risk.correlation_matrix(data).values
        np.testing.assert_allclose(corr, corr.T, atol=1e-12)
        for index in range(corr.shape[0]):
            assert corr[index, index] == pytest.approx(1.0)
            other = (index + 1) % corr.shape[0]
            assert -1.0 - 1e-12 <= corr[index, other] <= 1.0 + 1e-12

    def test_numerical_stability_against_reference_literal(self) -> None:
        data = np.array([[10.0, 40.0], [20.0, 30.0], [30.0, 20.0], [40.0, 10.0]])
        corr = risk.correlation_matrix(data).values
        assert corr[0, 1] == pytest.approx(-0.9)
        assert corr[1, 0] == pytest.approx(-0.9)
