"""Tests for the Terminal Echo Cloudflare Data API proxy."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.util import get_remote_address


@pytest.mark.unit
def test_terminal_quotes_proxy_uses_dataapi_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import terminal_data
    from api.terminal_data import register_terminal_data_routes
    from auth import get_current_user
    from settings import Settings

    calls: list[tuple[str, list[str] | None]] = []

    class FakeBridge:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def configured(self) -> bool:
            return True

        async def get_json(self, path: str, *, scopes: list[str] | None = None) -> dict[str, Any]:
            calls.append((path, scopes))
            return {
                "quotes": [
                    {
                        "ticker": "AAPL",
                        "company_name": "Apple Inc.",
                        "last_price": 201.5,
                        "price_change_pct": 1.25,
                        "rsi_14": 58.0,
                        "updated_at": "2026-06-19T12:00:00Z",
                    }
                ]
            }

    monkeypatch.setattr(terminal_data, "DataApiBridge", FakeBridge)

    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.state.settings = Settings.model_construct(
        admin_dataapi_url="https://dataapiprod.theeyebeta.store",
        dataapi_tunnel_url="https://dataapiprod.theeyebeta.store",
        admin_dataapi_client_id="client",
        admin_dataapi_client_secret="secret",
    )

    async def _fake_user() -> dict[str, Any]:
        return {"sub": "operator", "roles": ["operator"]}

    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(register_terminal_data_routes(app.state.limiter), prefix="/admin")

    with TestClient(app) as client:
        response = client.get("/admin/terminal-data/quotes?symbols=AAPL,AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["quotes"][0]["ticker"] == "AAPL"
    assert body["symbols"] == ["AAPL"]
    assert body["source"]["provider"] == "cloudflare-dataapi"
    assert calls == [("/api/v1/market-data/quotes?symbols=AAPL", ["market:read"])]


@pytest.mark.unit
def test_terminal_quotes_rejects_invalid_symbol() -> None:
    from api.terminal_data import register_terminal_data_routes
    from auth import get_current_user
    from settings import Settings

    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.state.settings = Settings.model_construct(
        admin_dataapi_url="https://dataapiprod.theeyebeta.store",
        dataapi_tunnel_url="https://dataapiprod.theeyebeta.store",
        admin_dataapi_client_id="client",
        admin_dataapi_client_secret="secret",
    )

    async def _fake_user() -> dict[str, Any]:
        return {"sub": "operator", "roles": ["operator"]}

    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(register_terminal_data_routes(app.state.limiter), prefix="/admin")

    with TestClient(app) as client:
        response = client.get("/admin/terminal-data/quotes?symbols=AAPL,$BAD")

    assert response.status_code == 422


@pytest.mark.unit
def test_terminal_indicators_proxy_uses_analytics_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import terminal_data
    from api.terminal_data import register_terminal_data_routes
    from auth import get_current_user
    from settings import Settings

    calls: list[tuple[str, list[str] | None]] = []

    class FakeBridge:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def configured(self) -> bool:
            return True

        async def get_json(self, path: str, *, scopes: list[str] | None = None) -> dict[str, Any]:
            calls.append((path, scopes))
            return {"ticker": "AAPL", "indicators": [{"date": "2026-06-19", "rsi_14": 58.0}]}

    monkeypatch.setattr(terminal_data, "DataApiBridge", FakeBridge)

    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address)
    app.state.settings = Settings.model_construct(
        admin_dataapi_url="https://dataapiprod.theeyebeta.store",
        dataapi_tunnel_url="https://dataapiprod.theeyebeta.store",
        admin_dataapi_client_id="client",
        admin_dataapi_client_secret="secret",
    )

    async def _fake_user() -> dict[str, Any]:
        return {"sub": "operator", "roles": ["operator"]}

    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(register_terminal_data_routes(app.state.limiter), prefix="/admin")

    with TestClient(app) as client:
        response = client.get("/admin/terminal-data/indicators/AAPL/technical?start=2026-01-01&limit=30")

    assert response.status_code == 200
    assert response.json()["indicators"][0]["rsi_14"] == 58.0
    assert calls[-1] == (
        "/api/v1/indicators/AAPL/technical?start=2026-01-01&limit=30",
        ["analytics:read"],
    )


@pytest.mark.unit
def test_terminal_modules_includes_live_and_planned_pages() -> None:
    from api.terminal_data import register_terminal_data_routes
    from auth import get_current_user

    app = FastAPI()
    app.state.limiter = Limiter(key_func=get_remote_address)

    async def _fake_user() -> dict[str, Any]:
        return {"sub": "operator", "roles": ["operator"]}

    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(register_terminal_data_routes(app.state.limiter), prefix="/admin")

    with TestClient(app) as client:
        response = client.get("/admin/terminal-data/modules")

    assert response.status_code == 200
    body = response.json()
    modules = {
        module["key"]
        for group in body["groups"]
        for module in group["modules"]
    }
    assert "risk" in modules
    assert "compliance" in modules
    assert "audit" in modules
    assert "sector-rotation" in modules
    assert "universe-screener" in modules
    assert {surface["key"] for surface in body["market_surfaces"]} >= {"sector-rotation", "universe-churn"}
