"""Latency-target load test for ``GET /admin/orders/pending``.

Runs 100 concurrent virtual users against the FastAPI app (via ``ASGITransport``)
backed by a real Postgres testcontainer for ~60 seconds and asserts that the
99th-percentile request latency stays under 500 ms — matching the production
SLO documented in ``docs/admin-service.md``.

The test is marked ``load``: default test runs (``pytest -m "not load"``) skip
it. Invoke explicitly with::

    uv run --package admin-service python -m pytest \\
        services/admin_service/tests/test_load.py -m load -v

Pair this with the k6 script ``scripts/load_admin_orders.js`` to drive load
against a live deployment over Cloudflare or Tailscale (see manual checklist
in ``docs/admin-service.md``).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import statistics
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)


# Tunables — overridable from the environment so CI can shorten the run.
CONCURRENT_USERS = int(os.getenv("ADMIN_LOAD_USERS", "100"))
DURATION_SECONDS = float(os.getenv("ADMIN_LOAD_DURATION_S", "60"))
P99_BUDGET_MS = float(os.getenv("ADMIN_LOAD_P99_BUDGET_MS", "500"))
ERROR_BUDGET = float(os.getenv("ADMIN_LOAD_ERROR_BUDGET", "0.01"))  # 1 % of requests


async def _build_loaded_client(
    dsn: str,
) -> AsyncIterator[AsyncClient]:
    """Yield an ASGI-backed httpx client wired to a seeded Postgres DSN."""
    from auth import get_current_user  # noqa: PLC0415

    from services.admin_service.tests.conftest import _admin_create_app  # noqa: PLC0415

    create_app = _admin_create_app()
    from settings import Settings, get_settings  # noqa: PLC0415

    get_settings.cache_clear()
    settings = Settings(database_url=dsn)
    with (
        patch("deps.init_resources", _admin_conf._init_test_resources),
        patch("deps.close_resources", _admin_conf._close_test_resources),
    ):
        app = create_app(settings=settings)
        await _admin_conf._init_test_resources(settings)
        import deps  # noqa: PLC0415

        deps.bind_app_state(app, settings)

        async def _fake_user() -> dict[str, str]:
            return {"sub": "load-test"}

        app.dependency_overrides[get_current_user] = _fake_user

        # Disable rate limiting for the load run — we are measuring the read
        # path's latency, not the slowapi middleware (which has its own tests).
        from slowapi import Limiter  # noqa: PLC0415

        limiter: Limiter = app.state.limiter
        limiter.enabled = False

        transport = ASGITransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            await _admin_conf._close_test_resources()


async def _virtual_user(
    client: AsyncClient,
    *,
    deadline: float,
    durations_ms: list[float],
    errors: list[int],
    barrier: asyncio.Event,
) -> None:
    """Hammer the endpoint until ``deadline`` and record per-call latency."""
    await barrier.wait()
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        try:
            response = await client.get(
                "/admin/orders/pending",
                headers={"Authorization": "Bearer load-test"},
            )
        except Exception:  # noqa: BLE001 — count any client-side error
            errors.append(0)
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        durations_ms.append(elapsed_ms)
        if response.status_code != 200:
            errors.append(response.status_code)


def _percentile(values: list[float], pct: float) -> float:
    """Return the linearly interpolated ``pct``-th percentile of ``values``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    fraction = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * fraction


@pytest.mark.load
@pytest.mark.asyncio
async def test_orders_pending_p99_under_500ms(
    orders_integration_dsn: str,
) -> None:
    """100 concurrent users for 60s on ``/admin/orders/pending``; p99 < 500 ms."""
    async for client in _build_loaded_client(orders_integration_dsn):
        durations_ms: list[float] = []
        errors: list[int] = []
        barrier = asyncio.Event()
        deadline = time.perf_counter() + DURATION_SECONDS
        tasks = [
            asyncio.create_task(
                _virtual_user(
                    client,
                    deadline=deadline,
                    durations_ms=durations_ms,
                    errors=errors,
                    barrier=barrier,
                ),
            )
            for _ in range(CONCURRENT_USERS)
        ]
        # Release all VUs at the same instant.
        barrier.set()
        started_wall = time.perf_counter()
        await asyncio.gather(*tasks)
        wall_clock_seconds = time.perf_counter() - started_wall

        total = len(durations_ms) + len(errors)
        assert total > 0, "load test produced no requests"
        p50 = _percentile(durations_ms, 50)
        p95 = _percentile(durations_ms, 95)
        p99 = _percentile(durations_ms, 99)
        max_ms = max(durations_ms) if durations_ms else 0.0
        rps = total / wall_clock_seconds if wall_clock_seconds else 0.0
        error_rate = len(errors) / total

        # Print metrics to stdout for CI artifacts (pytest -s will surface).
        print(  # noqa: T201
            "\nadmin-load summary: "
            f"users={CONCURRENT_USERS} duration_s={wall_clock_seconds:.1f} "
            f"requests={total} rps={rps:.1f} errors={len(errors)} "
            f"p50_ms={p50:.1f} p95_ms={p95:.1f} p99_ms={p99:.1f} "
            f"max_ms={max_ms:.1f}",
        )

        assert error_rate <= ERROR_BUDGET, (
            f"error_rate={error_rate:.4f} exceeds budget {ERROR_BUDGET:.4f} "
            f"(non-200 codes: {sorted(set(errors))})"
        )
        assert p99 <= P99_BUDGET_MS, (
            f"p99 latency {p99:.1f}ms exceeds budget {P99_BUDGET_MS:.1f}ms "
            f"(p50={p50:.1f}ms, p95={p95:.1f}ms, max={max_ms:.1f}ms, "
            f"requests={total}, rps={rps:.1f})"
        )
        # Sanity: median should also be sub-budget on a hot path.
        assert statistics.median(durations_ms) <= P99_BUDGET_MS
