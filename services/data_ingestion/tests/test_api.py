"""HTTP API tests for the data-ingestion FastAPI app."""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


def _load_main_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("data_ingestion_main", _MAIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app() -> FastAPI:
    """FastAPI application instance (module-level singleton)."""
    main = _load_main_module()
    return main.app


@pytest.mark.asyncio
async def test_health_returns_ok(app: FastAPI) -> None:
    """GET /health returns 200 with status ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "data-ingestion"
