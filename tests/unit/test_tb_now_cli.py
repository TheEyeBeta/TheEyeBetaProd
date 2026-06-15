"""Unit tests for ``tb now`` CLI."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from tb.commands.now import app

runner = CliRunner()


def test_now_price_found() -> None:
    with patch(
        "tb.commands.now.asyncio.run",
        return_value={
            "symbol": "AAPL",
            "instrument_id": 1,
            "price": {"d": "2026-06-12", "close": 150.0, "volume": 1_000},
        },
    ):
        result = runner.invoke(app, ["price", "AAPL"])
    assert result.exit_code == 0
    assert "AAPL" in result.stdout


def test_now_price_missing() -> None:
    with patch("tb.commands.now.asyncio.run", return_value=None):
        result = runner.invoke(app, ["price", "ZZZZ"])
    assert result.exit_code == 1
