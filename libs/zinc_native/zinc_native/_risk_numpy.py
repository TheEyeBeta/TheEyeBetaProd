"""NumPy fallback for zinc::risk when ``_zinc_risk`` is not compiled."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class CorrelationMatrix:
    """Pearson correlation matrix wrapper matching the C++ binding."""

    values: np.ndarray
    rows: int
    cols: int


def _as_array(samples: np.ndarray | list[float]) -> np.ndarray:
    return np.asarray(samples, dtype=float)


def _lower_quantile_index(size: int, alpha: float) -> int:
    return max(0, int(np.floor(alpha * (size - 1))))


def historical_var(samples: np.ndarray | list[float], alpha: float) -> float:
    """Historical VaR at tail probability ``alpha`` (lower tail)."""
    arr = _as_array(samples)
    if arr.size == 0 or alpha <= 0.0 or alpha >= 1.0:
        return float(np.nan)
    if arr.size == 1:
        return float(arr[0])
    index = _lower_quantile_index(arr.size, alpha)
    return float(np.partition(arr, index)[index])


def cvar(samples: np.ndarray | list[float], alpha: float) -> float:
    """Conditional VaR (expected shortfall) at tail probability ``alpha``."""
    arr = _as_array(samples)
    if arr.size == 0 or alpha <= 0.0 or alpha >= 1.0:
        return float(np.nan)
    if arr.size == 1:
        return float(arr[0])
    threshold = historical_var(arr, alpha)
    tail = arr[arr <= threshold]
    if tail.size == 0:
        return threshold
    return float(np.mean(tail))


def max_drawdown(wealth: np.ndarray | list[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction of the running peak."""
    arr = _as_array(wealth)
    if arr.size == 0:
        return float(np.nan)
    peak = arr[0]
    if not peak > 0.0:
        return float(np.nan)
    worst = 0.0
    for value in arr:
        if not value > 0.0:
            return float(np.nan)
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst


def correlation_matrix(data: np.ndarray) -> CorrelationMatrix:
    """Pearson correlation matrix for column-wise observations."""
    matrix = np.asarray(data, dtype=float)
    if matrix.ndim != 2:
        msg = "data must be a 2-D array"
        raise ValueError(msg)
    rows, cols = matrix.shape
    if cols == 0:
        return CorrelationMatrix(values=np.empty((0, 0)), rows=0, cols=0)
    if rows == 0:
        nan_block = np.full((cols, cols), np.nan)
        np.fill_diagonal(nan_block, 1.0)
        return CorrelationMatrix(values=nan_block, rows=cols, cols=cols)
    if rows == 1:
        identity = np.eye(cols)
        if cols > 1:
            identity[0, 1:] = np.nan
            identity[1:, 0] = np.nan
        return CorrelationMatrix(values=identity, rows=cols, cols=cols)
    corr = np.corrcoef(matrix, rowvar=False)
    if corr.ndim == 0:
        corr = np.array([[float(corr)]])
    return CorrelationMatrix(values=corr, rows=cols, cols=cols)
