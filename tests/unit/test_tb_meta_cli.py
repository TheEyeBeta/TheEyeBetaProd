"""Unit tests for ``tb meta`` CLI."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from tb.commands.meta import app

runner = CliRunner()


def test_meta_cheat() -> None:
    result = runner.invoke(app, ["cheat"])
    assert result.exit_code == 0
    assert "tb status" in result.stdout


def test_meta_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "tb" in result.stdout


def test_meta_doctor_pass() -> None:
    with (
        patch("tb.commands.meta.asyncio.run", return_value={"ok": True, "active_eod_universe": 100}),
        patch("tb.commands.meta.shutil.disk_usage", return_value=type("U", (), {"free": 80, "total": 100})()),
        patch("tb.commands.meta.list_timers", return_value="theeye-massive-ingest.timer"),
    ):
        result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "PASS" in result.stdout
