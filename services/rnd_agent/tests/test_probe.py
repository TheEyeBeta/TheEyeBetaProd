"""Unit tests for readonly role startup probe."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rnd_agent.probe import ReadonlyRoleProbeError, verify_readonly_role  # noqa: E402

_DENIED = psycopg.errors.InsufficientPrivilege("denied")


def _mock_conn(*, execute_results: list[object]) -> MagicMock:
    """Context manager mock whose ``execute`` uses a configured side effect."""
    conn = MagicMock()
    conn.execute.side_effect = execute_results
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = False
    return ctx


@pytest.mark.unit
def test_probe_passes_when_privileges_denied() -> None:
    """Probe succeeds when UPDATE/SELECT raise InsufficientPrivilege."""
    ctx = _mock_conn(execute_results=[_DENIED, _DENIED])

    with patch("rnd_agent.probe.psycopg.connect", return_value=ctx):
        verify_readonly_role("postgresql://tb_rnd_readonly:x@127.0.0.1:5432/theeyebeta")

    assert ctx.__enter__.return_value.execute.call_count == 2


@pytest.mark.unit
def test_probe_fails_when_update_succeeds() -> None:
    """Probe aborts when instruments UPDATE is allowed."""
    ctx = _mock_conn(execute_results=[None, _DENIED])

    with (
        patch("rnd_agent.probe.psycopg.connect", return_value=ctx),
        pytest.raises(ReadonlyRoleProbeError, match="instruments"),
    ):
        verify_readonly_role("postgresql://tb_rnd_readonly:x@127.0.0.1:5432/theeyebeta")


@pytest.mark.unit
def test_probe_fails_when_audit_select_succeeds() -> None:
    """Probe aborts when audit_log SELECT is allowed."""
    ctx = _mock_conn(execute_results=[_DENIED, None])

    with (
        patch("rnd_agent.probe.psycopg.connect", return_value=ctx),
        pytest.raises(ReadonlyRoleProbeError, match="audit_log"),
    ):
        verify_readonly_role("postgresql://tb_rnd_readonly:x@127.0.0.1:5432/theeyebeta")
