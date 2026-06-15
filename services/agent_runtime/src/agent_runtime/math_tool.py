"""LLM-callable ``compute_stat`` tool backed by zinc_native kernels."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import numpy as np
import structlog
from pydantic import BaseModel, ConfigDict, Field

from zinc_schemas.llm_client import LLMClient

log = structlog.get_logger()

Kernel = Literal["ta", "risk", "opt"]


class ComputeStatRequest(BaseModel):
    """Arguments for the ``compute_stat`` tool."""

    model_config = ConfigDict(extra="forbid")

    kernel: Kernel
    operation: str = Field(description="Kernel operation name, e.g. rsi, historical_var, mvo.")
    params: dict[str, Any] = Field(default_factory=dict)


class ComputeStatResponse(BaseModel):
    """Structured result from a ``compute_stat`` invocation."""

    model_config = ConfigDict(extra="forbid")

    kernel: Kernel
    operation: str
    result: Any


def openai_tool_definition() -> dict[str, Any]:
    """Return the OpenAI tool schema for ``compute_stat``."""
    schema = ComputeStatRequest.model_json_schema()
    schema.pop("$defs", None)
    return {
        "type": "function",
        "function": {
            "name": "compute_stat",
            "description": (
                "Run a deterministic numeric kernel (ta, risk, or opt) on snapshot-derived "
                "arrays. Use only for calculations not already present in the snapshot."
            ),
            "parameters": schema,
        },
    }


def _as_float_array(values: Any, *, name: str) -> np.ndarray:  # noqa: ANN401 — accepts arbitrary JSON-decoded input before type-checking
    if not isinstance(values, list) or not values:
        msg = f"{name} must be a non-empty list of numbers"
        raise ValueError(msg)
    return np.asarray(values, dtype=np.float64)


def _as_ohlc_matrix(rows: Any) -> np.ndarray:  # noqa: ANN401 — accepts arbitrary JSON-decoded input before type-checking
    if not isinstance(rows, list) or not rows:
        msg = "ohlc must be a non-empty list of [open, high, low, close] rows"
        raise ValueError(msg)
    matrix = np.asarray(rows, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 4:
        msg = "ohlc must be shape (n, 4)"
        raise ValueError(msg)
    return matrix


def _dispatch(req: ComputeStatRequest) -> Any:  # noqa: ANN401 — dispatch returns heterogeneous kernel results
    """Execute the requested zinc_native kernel operation."""
    op = req.operation.strip().lower()
    params = req.params

    if req.kernel == "ta":
        from zinc_native import ta  # noqa: PLC0415

        if op == "rsi":
            closes = _as_float_array(params.get("closes"), name="closes")
            period = int(params.get("period", 14))
            return ta.rsi(closes, period).tolist()
        if op == "atr":
            ohlc = _as_ohlc_matrix(params.get("ohlc"))
            period = int(params.get("period", 14))
            return ta.atr(ohlc, period).tolist()
        if op == "adx":
            ohlc = _as_ohlc_matrix(params.get("ohlc"))
            period = int(params.get("period", 14))
            return ta.adx(ohlc, period).tolist()
        if op == "zscore":
            closes = _as_float_array(params.get("closes"), name="closes")
            period = int(params.get("period", 20))
            return ta.zscore(closes, period).tolist()
        if op == "bollinger":
            closes = _as_float_array(params.get("closes"), name="closes")
            period = int(params.get("period", 20))
            std_mult = float(params.get("std_mult", 2.0))
            bands = ta.bollinger(closes, period, std_mult)
            return {
                "upper": bands.upper.tolist(),
                "middle": bands.middle.tolist(),
                "lower": bands.lower.tolist(),
            }
        msg = f"Unknown ta operation: {req.operation}"
        raise ValueError(msg)

    if req.kernel == "risk":
        from zinc_native import risk  # noqa: PLC0415

        samples = _as_float_array(params.get("samples"), name="samples")
        if op == "historical_var":
            return float(risk.historical_var(samples, float(params.get("alpha", 0.05))))
        if op == "cvar":
            return float(risk.cvar(samples, float(params.get("alpha", 0.05))))
        if op == "max_drawdown":
            return float(risk.max_drawdown(samples))
        if op == "correlation_matrix":
            matrix = np.asarray(params.get("returns_matrix"), dtype=np.float64)
            cm = risk.correlation_matrix(matrix)
            return {"matrix": cm.matrix.tolist()}
        msg = f"Unknown risk operation: {req.operation}"
        raise ValueError(msg)

    if req.kernel == "opt":
        from zinc_native import opt  # noqa: PLC0415

        if op == "mvo":
            expected = _as_float_array(params.get("expected_returns"), name="expected_returns")
            cov = np.asarray(params.get("covariance"), dtype=np.float64)
            weights = opt.mvo(expected, cov)
            return {"weights": weights.weights.tolist()}
        if op == "hrp":
            cov = np.asarray(params.get("covariance"), dtype=np.float64)
            weights = opt.hrp(cov)
            return {"weights": weights.weights.tolist()}
        if op == "black_litterman":
            cov = np.asarray(params.get("covariance"), dtype=np.float64)
            market_weights = _as_float_array(
                params.get("market_weights"),
                name="market_weights",
            )
            picking_matrix = np.asarray(params.get("picking_matrix"), dtype=np.float64)
            view_returns = _as_float_array(params.get("view_returns"), name="view_returns")
            view_uncertainty = _as_float_array(
                params.get("view_uncertainty"),
                name="view_uncertainty",
            )
            weights = opt.black_litterman(
                cov,
                market_weights,
                picking_matrix,
                view_returns,
                view_uncertainty,
                risk_aversion=float(params.get("risk_aversion", 2.5)),
                tau=float(params.get("tau", 0.05)),
            )
            return {"weights": weights.weights.tolist()}
        msg = f"Unknown opt operation: {req.operation}"
        raise ValueError(msg)

    msg = f"Unknown kernel: {req.kernel}"
    raise ValueError(msg)


class MathTool:
    """Expose ``compute_stat`` to the LLM with model_runs auditing."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        """Optional LLM client used to persist tool_call rows."""
        self._llm_client = llm_client

    async def compute_stat(self, request: ComputeStatRequest) -> ComputeStatResponse:
        """Run one kernel operation and log to ``model_runs``."""
        t0 = time.perf_counter()
        status = "ok"
        try:
            result = _dispatch(request)
            return ComputeStatResponse(
                kernel=request.kernel,
                operation=request.operation,
                result=result,
            )
        except Exception:
            status = "error"
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if self._llm_client is not None:
                await self._llm_client.record_tool_run(
                    tool_name=f"compute_stat:{request.kernel}.{request.operation}",
                    latency_ms=latency_ms,
                    status=status,
                )

    async def handle_tool_call(self, arguments_json: str) -> str:
        """Parse JSON arguments, execute, and return a JSON string for the LLM."""
        payload = json.loads(arguments_json)
        req = ComputeStatRequest.model_validate(payload)
        resp = await self.compute_stat(req)
        return resp.model_dump_json()
