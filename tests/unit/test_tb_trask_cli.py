"""Unit tests for ``tb trask`` CLI."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from tb.commands.trask import app

runner = CliRunner()


def test_trask_workers_lists_components() -> None:
    with patch("tb.commands.trask._trask_workers_async", AsyncMock()) as mock:
        result = runner.invoke(app, ["workers"])
    assert result.exit_code == 0
    mock.assert_awaited_once()


def test_trask_status_healthy() -> None:
    with patch("tb.commands.trask._trask_status_async", AsyncMock()) as mock:
        result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    mock.assert_awaited_once()


def test_trask_dashboard() -> None:
    with patch("tb.commands.trask._trask_dashboard_async", AsyncMock()) as mock:
        result = runner.invoke(app, ["dashboard", "--once"])
    assert result.exit_code == 0
    mock.assert_awaited_once()
