"""Tests for submission gate blocking approve."""

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

from oms.app import create_app  # noqa: E402
from oms.settings import Settings  # noqa: E402
from oms.submission_gate import PauseSource, SubmissionGate  # noqa: E402

ORDER_ID = uuid4()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_returns_423_when_submissions_paused() -> None:
    """POST approve is blocked while reconciliation pause is active."""
    settings = Settings(
        database_url="postgresql://test:test@localhost/db",
        nats_url="nats://127.0.0.1:4222",
    )
    gate = SubmissionGate(redis_url=None)
    await gate.pause(source=PauseSource.RECONCILIATION, reason="test drift")

    with (
        patch("oms.app.SubmissionGate", return_value=gate),
        patch("oms.reconciliation.ReconciliationLoop.start", AsyncMock()),
        patch("oms.reconciliation.ReconciliationLoop.stop", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.start", AsyncMock()),
        patch("oms.consumer.OmsEventConsumer.stop", AsyncMock()),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(f"/oms/orders/{ORDER_ID}/approve")

    assert response.status_code == 423
