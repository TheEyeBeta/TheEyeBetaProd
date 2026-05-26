"""Load test: 100 concurrent ValidateAgentOutput calls (p95 < 80ms, no Haiku)."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_AGENT = "macro-lead"
_CONCURRENT = 100
_P95_MS_LIMIT = 80.0

_VALID_OUTPUT = json.dumps(
    {
        "market_stance": "neutral",
        "regime_call": "ranging",
        "decisions": [
            {
                "instrument_symbol": "AAPL",
                "decision": "HOLD",
                "confidence": 0.65,
                "horizon_days": 10,
                "key_drivers": ["macro.us.dgs10 stable", "technicals.AAPL.rsi14 neutral"],
                "rationale": (
                    "technicals.AAPL.rsi14 at 55; macro.us.dgs10 at 4.25 "
                    "implies range-bound conditions."
                ),
            },
        ],
    },
)

_SNAPSHOT = {
    "market": "US",
    "universe": [{"symbol": "AAPL", "instrument_id": 1}],
    "technicals": {"AAPL": {"rsi14": 55.0}},
    "prices": {"AAPL": {"close": 105.0}},
    "macro": {"us.dgs10": 4.25},
}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


@pytest.fixture
def guard_http_app(monkeypatch: pytest.MonkeyPatch):
    """In-process guard-service HTTP app without Haiku classifier or DB I/O."""
    monkeypatch.setenv("GUARD_DISABLE_CREATIVE_CLASSIFIER", "1")
    from guard_service.app import build_guard, create_http_app  # noqa: PLC0415

    return create_http_app(build_guard())


@pytest.mark.load
@pytest.mark.asyncio
async def test_validate_agent_output_load_p95_under_80ms(guard_http_app) -> None:
    """100 concurrent validations against guard-service; p95 latency < 80ms."""
    transport = httpx.ASGITransport(app=guard_http_app)
    latencies_ms: list[float] = []

    async def _one(client: httpx.AsyncClient) -> None:
        run_id = str(uuid4())
        payload = {
            "agent_id": _AGENT,
            "run_id": run_id,
            "raw_output": _VALID_OUTPUT,
            "valid_symbols": ["AAPL"],
            "snapshot": _SNAPSHOT,
            "tool_calls": [],
        }
        t0 = time.perf_counter()
        response = await client.post("/v1/validate-agent-output", json=payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)
        response.raise_for_status()
        body = response.json()
        assert body["approved"] is True
        assert body["outcome"] == "PASS"

    with (
        patch("guard_service.app.count_violations_for_run", AsyncMock(return_value=0)),
        patch("guard_service.app.insert_violations", AsyncMock()),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://guard") as client:
            await asyncio.gather(*[_one(client) for _ in range(_CONCURRENT)])

    p50 = statistics.median(latencies_ms)
    p95 = _percentile(latencies_ms, 95.0)
    p99 = _percentile(latencies_ms, 99.0)
    assert p95 < _P95_MS_LIMIT, (
        f"p95 {p95:.1f}ms exceeds {_P95_MS_LIMIT}ms "
        f"(p50={p50:.1f} p99={p99:.1f} n={len(latencies_ms)})"
    )


@pytest.mark.load
@pytest.mark.integration
@pytest.mark.asyncio
async def test_validate_agent_output_load_http_service() -> None:
    """Optional load test against a running guard-service (GUARD_SERVICE_HTTP_URL)."""
    import os  # noqa: PLC0415

    base = os.environ.get("GUARD_SERVICE_HTTP_URL", "").rstrip("/")
    if not base:
        pytest.skip("GUARD_SERVICE_HTTP_URL not set")

    async with httpx.AsyncClient(timeout=10.0) as probe:
        try:
            health = await probe.get(f"{base}/health")
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"guard-service not reachable: {exc}")

    latencies_ms: list[float] = []

    async def _one(client: httpx.AsyncClient) -> None:
        payload = {
            "agent_id": _AGENT,
            "run_id": str(uuid4()),
            "raw_output": _VALID_OUTPUT,
            "valid_symbols": ["AAPL"],
            "snapshot": _SNAPSHOT,
        }
        t0 = time.perf_counter()
        response = await client.post(f"{base}/v1/validate-agent-output", json=payload)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        response.raise_for_status()
        assert response.json()["outcome"] == "PASS"

    async with httpx.AsyncClient(timeout=30.0) as client:
        await asyncio.gather(*[_one(client) for _ in range(_CONCURRENT)])

    p95 = _percentile(latencies_ms, 95.0)
    assert p95 < _P95_MS_LIMIT, f"remote p95 {p95:.1f}ms exceeds {_P95_MS_LIMIT}ms"
