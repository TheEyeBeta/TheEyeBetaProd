"""HTTP endpoint tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backtest_engine.app import create_app  # noqa: E402
from backtest_engine.settings import Settings  # noqa: E402

RUN_ID = uuid4()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_endpoint_returns_running_id() -> None:
    """POST /backtest/run returns backtest_run_id immediately."""
    settings = Settings(database_url="postgresql://test:test@localhost/db")
    app = create_app(settings)

    with (
        patch("backtest_engine.db.insert_backtest_run", AsyncMock(return_value=RUN_ID)),
        patch("backtest_engine.runner.BacktestRunner.run", AsyncMock()),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/backtest/run",
                json={
                    "strategy_id": "example_swing_us",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "walk_forward": False,
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["backtest_run_id"] == str(RUN_ID)
    assert body["status"] == "running"
