"""pytest mirrors of cpp/tests/opt_*_test.cpp."""

from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("zinc_native._zinc_opt", reason="C++ kernels not compiled — run make build-cpp")
from zinc_native import opt


def _weights_valid(weights: np.ndarray) -> bool:
    if weights.size == 0:
        return False
    if np.any(weights < -1e-12):
        return False
    return abs(float(weights.sum()) - 1.0) < 1e-8


class TestMvo:
    def test_happy_path_minimum_variance_hand_computed(self) -> None:
        expected_returns = np.zeros(2, dtype=np.float64)
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        result = opt.mvo(expected_returns, covariance, risk_aversion=1.0)
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (2,)
        assert weights[0] == pytest.approx(0.72726904, abs=1e-6)
        assert weights[1] == pytest.approx(0.27273096, abs=1e-6)
        assert _weights_valid(weights)

    def test_empty_and_invalid_input_returns_empty(self) -> None:
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        expected_returns = np.array([0.1, 0.05], dtype=np.float64)

        assert len(opt.mvo(np.array([]), covariance).weights) == 0
        assert len(opt.mvo(expected_returns, np.empty((0, 0))).weights) == 0
        assert len(opt.mvo(expected_returns, covariance, risk_aversion=0.0).weights) == 0

    def test_single_asset_returns_unit_weight(self) -> None:
        expected_returns = np.array([0.08], dtype=np.float64)
        covariance = np.array([[0.05]], dtype=np.float64)
        result = opt.mvo(expected_returns, covariance)
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (1,)
        assert weights[0] == pytest.approx(1.0)

    def test_random_covariance_produces_valid_long_only_weights(self) -> None:
        rng = np.random.default_rng(0x4D564F123)
        assets = 12
        factor = rng.normal(0.0, 1.0, size=(assets, assets))
        covariance = factor @ factor.T + np.eye(assets) * 1e-3
        expected_returns = rng.normal(0.0, 1.0, size=assets) * 0.01
        result = opt.mvo(expected_returns, covariance, risk_aversion=2.0)
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (assets,)
        assert _weights_valid(weights)

    def test_numerical_stability_scale_invariant_minimum_variance(self) -> None:
        expected_returns = np.zeros(2, dtype=np.float64)
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        base = np.asarray(opt.mvo(expected_returns, covariance, risk_aversion=1.0).weights)
        scaled = np.asarray(
            opt.mvo(expected_returns, covariance * 1.0e6, risk_aversion=1.0).weights
        )
        assert base.shape == scaled.shape
        np.testing.assert_allclose(base, scaled, atol=1e-6)


class TestBlackLitterman:
    def test_happy_path_hand_computed_posterior_weights(self) -> None:
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        market_weights = np.array([0.6, 0.4], dtype=np.float64)
        picking_matrix = np.array([[1.0, 0.0]], dtype=np.float64)
        view_returns = np.array([0.12], dtype=np.float64)
        view_uncertainty = np.array([0.001], dtype=np.float64)

        result = opt.black_litterman(
            covariance,
            market_weights,
            picking_matrix,
            view_returns,
            view_uncertainty,
            risk_aversion=2.5,
            tau=0.05,
        )
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (2,)
        assert weights[0] == pytest.approx(0.69090909, abs=1e-5)
        assert weights[1] == pytest.approx(0.30909091, abs=1e-5)
        assert _weights_valid(weights)

    def test_empty_and_invalid_input_returns_empty(self) -> None:
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        market_weights = np.array([0.5, 0.5], dtype=np.float64)
        picking_matrix = np.eye(2, dtype=np.float64)
        view_returns = np.array([0.1, 0.05], dtype=np.float64)
        view_uncertainty = np.array([0.001, 0.001], dtype=np.float64)

        assert (
            len(
                opt.black_litterman(
                    np.empty((0, 0)),
                    market_weights,
                    picking_matrix,
                    view_returns,
                    view_uncertainty,
                ).weights
            )
            == 0
        )
        assert (
            len(
                opt.black_litterman(
                    covariance,
                    np.array([]),
                    picking_matrix,
                    view_returns,
                    view_uncertainty,
                ).weights
            )
            == 0
        )
        bad_uncertainty = np.array([0.0, 0.001], dtype=np.float64)
        assert (
            len(
                opt.black_litterman(
                    covariance,
                    market_weights,
                    picking_matrix,
                    view_returns,
                    bad_uncertainty,
                ).weights
            )
            == 0
        )

    def test_single_asset_returns_unit_weight(self) -> None:
        covariance = np.array([[0.02]], dtype=np.float64)
        market_weights = np.array([1.0], dtype=np.float64)
        picking_matrix = np.array([[1.0]], dtype=np.float64)
        view_returns = np.array([0.08], dtype=np.float64)
        view_uncertainty = np.array([0.001], dtype=np.float64)

        result = opt.black_litterman(
            covariance, market_weights, picking_matrix, view_returns, view_uncertainty
        )
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (1,)
        assert weights[0] == pytest.approx(1.0)

    def test_random_views_produce_valid_weights(self) -> None:
        rng = np.random.default_rng(0x0B142)
        assets = 8
        factor = rng.normal(0.0, 1.0, size=(assets, assets)) * 0.1
        covariance = factor @ factor.T + np.eye(assets) * 1e-2
        market_weights = np.full(assets, 1.0 / assets, dtype=np.float64)
        picking_matrix = np.eye(assets, dtype=np.float64)
        view_returns = 0.05 + 0.01 * rng.normal(0.0, 1.0, size=assets)
        view_uncertainty = 0.001 + np.abs(rng.normal(0.0, 1.0, size=assets)) * 0.0005

        result = opt.black_litterman(
            covariance,
            market_weights,
            picking_matrix,
            view_returns,
            view_uncertainty,
        )
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (assets,)
        assert _weights_valid(weights)

    def test_numerical_stability_scaled_covariance(self) -> None:
        covariance = np.array([[0.04, 0.01], [0.01, 0.09]], dtype=np.float64)
        market_weights = np.array([0.6, 0.4], dtype=np.float64)
        picking_matrix = np.array([[1.0, 0.0]], dtype=np.float64)
        view_returns = np.array([0.12], dtype=np.float64)
        view_uncertainty = np.array([0.001], dtype=np.float64)

        base = np.asarray(
            opt.black_litterman(
                covariance,
                market_weights,
                picking_matrix,
                view_returns,
                view_uncertainty,
            ).weights
        )
        scaled = np.asarray(
            opt.black_litterman(
                covariance * 1.0e6,
                market_weights,
                picking_matrix,
                view_returns,
                view_uncertainty,
            ).weights
        )
        np.testing.assert_allclose(base, scaled, atol=1e-5)


class TestHrp:
    def test_happy_path_equal_variance_diagonal_hand_computed(self) -> None:
        covariance = np.array([[0.04, 0.0], [0.0, 0.04]], dtype=np.float64)
        result = opt.hrp(covariance)
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (2,)
        assert weights[0] == pytest.approx(0.5, abs=1e-6)
        assert weights[1] == pytest.approx(0.5, abs=1e-6)
        assert _weights_valid(weights)

    def test_empty_and_invalid_input_returns_empty(self) -> None:
        assert len(opt.hrp(np.empty((0, 0))).weights) == 0
        rectangular = np.array([[0.04], [0.01]], dtype=np.float64)
        assert len(opt.hrp(rectangular).weights) == 0

    def test_single_asset_returns_unit_weight(self) -> None:
        covariance = np.array([[0.05]], dtype=np.float64)
        result = opt.hrp(covariance)
        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (1,)
        assert weights[0] == pytest.approx(1.0)

    def test_random_covariance_produces_valid_weights_under_one_hundred_ms(self) -> None:
        rng = np.random.default_rng(0x485250100)
        assets = 100
        factor = rng.normal(0.0, 1.0, size=(assets, assets)) * 0.05
        covariance = factor @ factor.T + np.eye(assets) * 1e-2

        start = time.perf_counter()
        result = opt.hrp(covariance)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        weights = np.asarray(result.weights, dtype=np.float64)
        assert weights.shape == (assets,)
        assert _weights_valid(weights)
        assert elapsed_ms < 100.0

    def test_numerical_stability_scale_invariant_weights(self) -> None:
        covariance = np.array([[0.04, 0.0], [0.0, 0.04]], dtype=np.float64)
        base = np.asarray(opt.hrp(covariance).weights)
        scaled = np.asarray(opt.hrp(covariance * 1.0e6).weights)
        np.testing.assert_allclose(base, scaled, atol=1e-6)
