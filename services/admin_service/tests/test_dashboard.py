"""Integration tests for the operator dashboard at ``GET /admin/``.

Covers the four stat cards, the htmx fragment endpoint, the two quick-action
buttons (audit verify + run daily backtest), the Grafana iframe, and auth.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_renders_with_seeded_stats(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/`` renders the four cards, action buttons, and iframe."""
    client, _ = dashboard_admin_client
    response = await client.get("/admin/", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text

    assert "Operator dashboard" in body
    assert 'id="stat-cards"' in body
    assert 'data-stat="pending-orders"' in body
    assert 'data-stat="active-agents"' in body
    assert 'data-stat="today-cost"' in body
    assert 'data-stat="audit-verify"' in body

    assert 'id="action-run-backtest"' in body
    assert 'id="action-verify-audit"' in body
    assert 'hx-post="/admin/actions/run-daily-backtest"' in body
    assert 'hx-post="/admin/actions/verify-audit-chain"' in body

    assert 'id="grafana-overview"' in body
    assert "<iframe" in body
    assert 'src="http://grafana:3000/d/overview' in body

    assert 'hx-get="/admin/fragments/stats"' in body
    assert 'hx-trigger="every 30s"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_stat_values_reflect_seed_data(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Counters in the response body match the dashboard seed."""
    client, _ = dashboard_admin_client
    response = await client.get("/admin/", headers=auth_headers)
    body = response.text

    pending_card = _slice_card(body, "pending-orders")
    assert ">2<" in pending_card

    agents_card = _slice_card(body, "active-agents")
    assert ">2<" in agents_card

    cost_card = _slice_card(body, "today-cost")
    assert "$2.00" in cost_card
    assert "LLM $1.50" in cost_card
    assert "API $0.50" in cost_card

    audit_card = _slice_card(body, "audit-verify")
    assert "Last sealed" in audit_card
    assert "dash-2026-05-25" in audit_card


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fragment_stats_returns_partial_only(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """``GET /admin/fragments/stats`` returns just the cards (no <html>)."""
    client, _ = dashboard_admin_client
    response = await client.get(
        "/admin/fragments/stats",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()
    assert 'data-test-id="stat-cards"' in body
    assert 'data-stat="pending-orders"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_dashboard_requires_auth(
    dashboard_integration_dsn: str,
) -> None:
    """No auth override → 401 on every dashboard route."""
    from auth import get_current_user  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    # Re-use the conftest helper without the dep override.
    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(
        database_url=dashboard_integration_dsn,
        audit_service_url="http://127.0.0.1:7110",
    )
    from httpx import ASGITransport  # noqa: PLC0415

    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        # Sanity: confirm the dep is wired but NOT overridden.
        assert get_current_user not in app.dependency_overrides
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/")
            frag = await anon.get("/admin/fragments/stats")
            verify = await anon.post("/admin/actions/verify-audit-chain")
            backtest = await anon.post("/admin/actions/run-daily-backtest")
    assert page.status_code == 401
    assert frag.status_code == 401
    assert verify.status_code == 401
    assert backtest.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_audit_chain_returns_updated_card(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """A successful audit-service call swaps the card with ``verified`` state."""
    client, _ = dashboard_admin_client

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"status": "OK", "first_bad_row_id": None, "rows_checked": 42}

        @property
        def text(self) -> str:
            return ""

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _url: str, params: dict[str, Any] | None = None) -> _Resp:
            assert params is not None
            assert "from" in params and "to" in params
            return _Resp()

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.post(
            "/admin/actions/verify-audit-chain",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.text
    assert 'id="audit-verify-card"' in body
    assert "Chain OK" in body
    assert "42" in body  # rows checked


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_audit_chain_handles_audit_service_failure(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """503 from audit-service surfaces as an error card, not a 500."""
    client, _ = dashboard_admin_client

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(
            self,
            _url: str,
            params: dict[str, Any] | None = None,  # noqa: ARG002
        ) -> Any:
            import httpx  # noqa: PLC0415

            raise httpx.ConnectError("connection refused")

    with patch("api.audit.httpx.AsyncClient", _StubClient):
        response = await client.post(
            "/admin/actions/verify-audit-chain",
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.text
    assert 'id="audit-verify-card"' in body
    assert "Verify failed" in body or "audit-service is unreachable" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_daily_backtest_warns_when_unconfigured(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """No ``ADMIN_DAILY_BACKTEST_STRATEGY_ID`` → friendly warn flash, not 500."""
    client, _ = dashboard_admin_client
    response = await client.post(
        "/admin/actions/run-daily-backtest",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "Daily backtest is not configured" in body
    assert response.headers.get("HX-Trigger", "").startswith("{")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_daily_backtest_happy_path(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """With a configured strategy the button proxies backtest-engine + flashes ok."""
    client, _ = dashboard_admin_client
    from deps import settings_dep  # noqa: PLC0415
    from settings import Settings  # noqa: PLC0415

    app = client._transport.app  # type: ignore[attr-defined]
    original_settings: Settings = app.state.settings
    override = Settings(
        database_url=original_settings.database_url,
        audit_service_url=original_settings.audit_service_url,
        backtest_engine_url="http://stub-engine:7100",
        daily_backtest_strategy_id="dash-strategy",
        daily_backtest_days=5,
    )

    async def _override_settings() -> Settings:
        return override

    new_run_id = str(uuid4())

    class _Resp:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {"backtest_run_id": new_run_id, "status": "running"}

        @property
        def text(self) -> str:
            return ""

    captured: list[tuple[str, dict[str, Any]]] = []

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> _Resp:
            captured.append((url, json))
            return _Resp()

    app.dependency_overrides[settings_dep] = _override_settings
    try:
        with patch("api.views.httpx.AsyncClient", _StubClient):
            response = await client.post(
                "/admin/actions/run-daily-backtest",
                headers=auth_headers,
            )
    finally:
        app.dependency_overrides.pop(settings_dep, None)

    assert response.status_code == 200
    body = response.text
    assert "queued" in body.lower()
    assert new_run_id[:8] in body

    assert len(captured) == 1
    url, payload = captured[0]
    assert url == "http://stub-engine:7100/backtest/run"
    assert payload["strategy_id"] == "dash-strategy"
    assert "start_date" in payload and "end_date" in payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_daily_backtest_engine_5xx_returns_error_flash(
    dashboard_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """A 5xx from backtest-engine becomes a flash error, not a 500."""
    client, _ = dashboard_admin_client
    from deps import settings_dep  # noqa: PLC0415
    from settings import Settings  # noqa: PLC0415

    app = client._transport.app  # type: ignore[attr-defined]
    original = app.state.settings

    async def _override_settings() -> Settings:
        return Settings(
            database_url=original.database_url,
            audit_service_url=original.audit_service_url,
            backtest_engine_url="http://stub-engine:7100",
            daily_backtest_strategy_id="dash-strategy",
        )

    class _Resp:
        status_code = 503

        @staticmethod
        def json() -> dict[str, Any]:
            return {}

        @property
        def text(self) -> str:
            return "engine down"

    class _StubClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def __aenter__(self) -> _StubClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, _url: str, json: dict[str, Any]) -> _Resp:  # noqa: ARG002
            return _Resp()

    app.dependency_overrides[settings_dep] = _override_settings
    try:
        with patch("api.views.httpx.AsyncClient", _StubClient):
            response = await client.post(
                "/admin/actions/run-daily-backtest",
                headers=auth_headers,
            )
    finally:
        app.dependency_overrides.pop(settings_dep, None)

    assert response.status_code == 200
    body = response.text
    assert "503" in body or "backtest-engine" in body
    assert "queued" not in body.lower()


def _slice_card(body: str, stat: str) -> str:
    """Return only the <article data-stat='…'> block for one stat card."""
    marker = f'data-stat="{stat}"'
    idx = body.find(marker)
    assert idx != -1, f"card {stat!r} not in body"
    end = body.find("</article>", idx)
    assert end != -1, f"card {stat!r} unterminated"
    return body[idx : end + len("</article>")]
