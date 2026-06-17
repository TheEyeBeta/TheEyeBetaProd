"""Integration tests for admin costs API."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient

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


def _current_month_str() -> str:
    today = datetime.now(tz=UTC).date()
    return f"{today.year:04d}-{today.month:02d}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_costs_happy(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/costs/daily aggregates model_runs + api_costs by day."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/daily",
        params={"days": 30},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 30
    assert len(body["entries"]) == 30

    # Newest first.
    dates = [date.fromisoformat(row["date"]) for row in body["entries"]]
    assert dates == sorted(dates, reverse=True)

    by_date: dict[date, dict[str, Decimal]] = {
        date.fromisoformat(row["date"]): {
            "model": Decimal(row["model_cost_usd"]),
            "api": Decimal(row["api_cost_usd"]),
            "total": Decimal(row["total_cost_usd"]),
        }
        for row in body["entries"]
    }
    today = datetime.now(tz=UTC).date()
    one_day_ago = today.fromordinal(today.toordinal() - 1)
    two_days_ago = today.fromordinal(today.toordinal() - 2)

    assert by_date[two_days_ago]["model"] == Decimal("0.100000")
    assert by_date[two_days_ago]["api"] == Decimal("1.5000")
    assert by_date[two_days_ago]["total"] == Decimal("1.6000")

    # 1 day ago: TA $0.05 + macro $0.20 = $0.25 model, $1.75 api.
    assert by_date[one_day_ago]["model"] == Decimal("0.250000")
    assert by_date[one_day_ago]["api"] == Decimal("1.7500")

    # Total ≥ all seeded current-month + previous-day api costs.
    assert Decimal(body["total_cost_usd"]) >= Decimal("3.6000")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_costs_validation(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """``days`` outside 1..365 fails Pydantic validation with 422."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/daily",
        params={"days": 0},
        headers=auth_headers,
    )
    assert response.status_code == 422
    response = await client.get(
        "/admin/costs/daily",
        params={"days": 9999},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_happy(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/costs/by-agent rolls model_runs up by agent for one month."""
    client, _ = costs_admin_client
    month = _current_month_str()
    response = await client.get(
        "/admin/costs/by-agent",
        params={"month": month},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == month
    by_agent = {row["agent_id"]: row for row in body["agents"]}

    assert "technical-analyst" in by_agent
    assert "macro-lead" in by_agent

    ta = by_agent["technical-analyst"]
    assert ta["runs"] == 1
    assert ta["model_runs"] == 2
    assert ta["input_tokens"] == 1500
    assert ta["output_tokens"] == 300
    assert Decimal(ta["cost_usd"]) == Decimal("0.150000")

    macro = by_agent["macro-lead"]
    assert macro["runs"] == 1
    assert macro["model_runs"] == 1
    assert Decimal(macro["cost_usd"]) == Decimal("0.200000")

    assert Decimal(body["total_cost_usd"]) == Decimal("0.350000")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_invalid_month(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Month string that doesn't match YYYY-MM returns 422."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/by-agent",
        params={"month": "2024/01"},
        headers=auth_headers,
    )
    assert response.status_code == 422
    response = await client.get(
        "/admin/costs/by-agent",
        params={"month": "2024-13"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_missing_param(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Missing ``month`` query parameter is a 422 (FastAPI default)."""
    client, _ = costs_admin_client
    response = await client.get("/admin/costs/by-agent", headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_empty_month(
    costs_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """A month with no model_runs returns an empty agents list."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/by-agent",
        params={"month": "2000-01"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agents"] == []
    assert Decimal(body["total_cost_usd"]) == Decimal("0")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_auth_required(costs_integration_dsn: str) -> None:
    """Both endpoints reject unauthenticated requests with 401."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=costs_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/costs/daily")).status_code == 401
            assert (
                await client.get("/admin/costs/by-agent", params={"month": "2024-01"})
            ).status_code == 401
