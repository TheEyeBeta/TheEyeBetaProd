"""Integration tests for ``/admin/costs`` (page + fragments).

Uses the existing ``seed_costs.sql`` fixture (2 agents, 4 model_runs across
the current and previous month, plus 2 api_costs rows for the last 2 days).
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


def _current_month_key() -> str:
    today = date.today()  # noqa: DTZ011 — calendar boundary
    return f"{today.year:04d}-{today.month:02d}"


def _extract_chart_config(body: str, chart_id: str) -> dict[str, Any]:
    """Pull the Chart.js JSON config emitted by a ``<script>`` next to ``canvas``."""
    match = re.search(
        rf'<script\s+id="{re.escape(chart_id)}-config"\s+type="application/json"\s*>'
        r"(.*?)</script>",
        body,
        re.DOTALL,
    )
    assert match is not None, f"chart config script not found for {chart_id}"
    return json.loads(match.group(1))


# ---------------------------------------------------------------- Page render


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_page_renders_both_charts_and_tables(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/costs`` renders the two charts + two MTD tables."""
    client, _ = costs_admin_client
    response = await client.get("/admin/costs", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    # Shell
    assert "Costs" in body
    assert 'aria-current="page"' in body
    # Daily chart + JSON config embedded inline
    assert 'data-test-id="costs-daily-card"' in body
    assert 'id="costs-daily-chart"' in body
    assert 'data-cost-chart="daily"' in body
    # Daily window selector
    assert 'name="days"' in body
    # By-agent doughnut + JSON config
    assert 'data-test-id="costs-agent-card"' in body
    assert 'id="costs-agent-chart"' in body
    assert 'data-cost-chart="by-agent"' in body
    # Vendor + agent tables
    assert 'data-test-id="costs-vendor-card"' in body
    assert 'data-test-id="costs-agent-table-card"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_page_daily_chart_has_30_day_window(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Daily chart defaults to 30 days, with 30 labels + LLM + API datasets."""
    client, _ = costs_admin_client
    response = await client.get("/admin/costs", headers=auth_headers)
    cfg = _extract_chart_config(response.text, "costs-daily-chart")
    assert cfg["type"] == "bar"
    assert len(cfg["data"]["labels"]) == 30
    labels_sorted = sorted(cfg["data"]["labels"])
    assert cfg["data"]["labels"] == labels_sorted, "labels must be ascending"
    datasets = cfg["data"]["datasets"]
    assert len(datasets) == 2
    assert datasets[0]["label"].startswith("LLM")
    assert datasets[1]["label"].startswith("API")
    # The seed inserted $0.10 + $0.05 + $0.20 LLM in the last 30 days.
    llm_total = sum(datasets[0]["data"])
    api_total = sum(datasets[1]["data"])
    assert llm_total == pytest.approx(0.35, rel=1e-3)
    assert api_total == pytest.approx(3.25, rel=1e-3)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_page_agent_doughnut_for_current_month(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Doughnut chart shows current-month per-agent share (TA = $0.15, macro = $0.20)."""
    client, _ = costs_admin_client
    response = await client.get("/admin/costs", headers=auth_headers)
    cfg = _extract_chart_config(response.text, "costs-agent-chart")
    assert cfg["type"] == "doughnut"
    labels = cfg["data"]["labels"]
    data = cfg["data"]["datasets"][0]["data"]
    assert set(labels) == {"technical-analyst", "macro-lead"}
    # macro-lead spent more than TA → comes first (ORDER BY cost_usd DESC).
    assert labels[0] == "macro-lead"
    assert data[0] == pytest.approx(0.20, rel=1e-3)
    assert data[1] == pytest.approx(0.15, rel=1e-3)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_page_vendor_table_lists_both_sources(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """MTD vendor table contains both LLM providers and API vendors."""
    client, _ = costs_admin_client
    response = await client.get("/admin/costs", headers=auth_headers)
    body = response.text
    # Vendor breakdown: openai (model) + anthropic (model) + polygon (api).
    assert 'data-vendor="openai"' in body
    assert 'data-vendor="anthropic"' in body
    assert 'data-vendor="polygon"' in body
    # LLM + API badges.
    assert ">LLM</span>" in body
    assert ">API</span>" in body


# ---------------------------------------------------------------- Fragment: daily


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_daily_fragment_partial(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Daily fragment is a partial (no ``<html>``) with the new ``days`` window."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/fragments/daily?days=7",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-test-id="costs-daily-card"' in body
    assert 'data-days="7"' in body
    cfg = _extract_chart_config(body, "costs-daily-chart")
    assert len(cfg["data"]["labels"]) == 7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_daily_fragment_rejects_invalid_days(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``days=0`` (or anything outside 1..365) is rejected with 422."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/fragments/daily?days=0",
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- Fragment: by-agent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_fragment_partial(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Per-agent fragment honours an explicit ``month`` query param."""
    client, _ = costs_admin_client
    month = _current_month_key()
    response = await client.get(
        f"/admin/costs/fragments/by-agent?month={month}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-test-id="costs-agent-card"' in body
    assert f'data-month="{month}"' in body
    cfg = _extract_chart_config(body, "costs-agent-chart")
    assert "technical-analyst" in cfg["data"]["labels"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_by_agent_fragment_rejects_invalid_month(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Bad ``YYYY-MM`` → 422."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/fragments/by-agent?month=2026-13",
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- Fragment: vendor


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_vendor_fragment_partial(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Vendor fragment is a partial showing the current-month vendor totals."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/fragments/vendor",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-test-id="costs-vendor-card"' in body
    # Same vendors as in the page render.
    assert 'data-vendor="openai"' in body
    assert 'data-vendor="anthropic"' in body
    assert 'data-vendor="polygon"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_vendor_fragment_rejects_invalid_month(
    costs_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Bad ``YYYY-MM`` → 422."""
    client, _ = costs_admin_client
    response = await client.get(
        "/admin/costs/fragments/vendor?month=not-a-month",
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------- Auth gate


@pytest.mark.integration
@pytest.mark.asyncio
async def test_costs_page_requires_auth(
    costs_integration_dsn: str,
) -> None:
    """All costs page routes are JWT-gated."""
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(database_url=costs_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/costs")
            daily = await anon.get("/admin/costs/fragments/daily")
            agent = await anon.get("/admin/costs/fragments/by-agent")
            vendor = await anon.get("/admin/costs/fragments/vendor")
    assert page.status_code == 401
    assert daily.status_code == 401
    assert agent.status_code == 401
    assert vendor.status_code == 401
