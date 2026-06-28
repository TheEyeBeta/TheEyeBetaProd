"""Unit tests for the MASTER_ADMIN control registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from api.master_admin import build_master_admin_control_matrix  # noqa: E402


@pytest.mark.unit
def test_master_admin_matrix_contains_controls_and_gaps() -> None:
    """The owner/operator registry is explicit about control gaps."""
    controls = build_master_admin_control_matrix()
    gaps = [
        entry
        for entry in controls
        if (not entry.api_exists) or entry.missing_backend_work or not entry.controllable
    ]

    assert len(controls) >= 10
    assert len(gaps) >= 1
    assert any(entry.feature == "Trading live approval and emergency halt" for entry in controls)
    assert any(not entry.api_exists for entry in gaps)
    assert all(entry.role_required for entry in controls)
    assert all(entry.priority in {"Critical", "High", "Medium", "Low"} for entry in controls)
