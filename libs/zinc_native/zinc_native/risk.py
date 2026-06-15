"""Python facade for ``zinc::risk`` (C++ ``_zinc_risk`` or NumPy fallback)."""

from __future__ import annotations

import structlog

log = structlog.get_logger()

try:
    from zinc_native._zinc_risk import (
        CorrelationMatrix,
        correlation_matrix,
        cvar,
        historical_var,
        max_drawdown,
    )
except ModuleNotFoundError:
    from zinc_native._risk_numpy import (
        CorrelationMatrix,
        correlation_matrix,
        cvar,
        historical_var,
        max_drawdown,
    )

    log.warning(
        "zinc_native.risk using NumPy fallback — run make build-cpp for C++ kernels",
    )

__all__ = [
    "CorrelationMatrix",
    "correlation_matrix",
    "cvar",
    "historical_var",
    "max_drawdown",
]
