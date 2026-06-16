"""Unit tests for RBAC role guards."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from rbac import Role, forbidden_error, highest_role, role_rank  # noqa: E402


@pytest.mark.unit
def test_role_hierarchy_order() -> None:
    """MASTER_ADMIN outranks OPERATOR and READ_ONLY."""
    assert role_rank("MASTER_ADMIN") > role_rank("OPERATOR")
    assert role_rank("OPERATOR") > role_rank("ANALYST")
    assert role_rank("ANALYST") > role_rank("READ_ONLY")


@pytest.mark.unit
def test_highest_role_picks_strongest() -> None:
    """Multiple roles resolve to the highest privilege."""
    assert highest_role(["READ_ONLY", "OPERATOR"]) == "OPERATOR"
    assert highest_role(["ANALYST", "MASTER_ADMIN"]) == "MASTER_ADMIN"


@pytest.mark.unit
def test_forbidden_error_shape() -> None:
    """403 errors use deterministic nested structure."""
    exc = forbidden_error(required_role="MASTER_ADMIN", actor_role="OPERATOR")
    assert exc.status_code == 403
    detail = exc.detail
    assert detail["error"]["code"] == "forbidden"
    assert detail["error"]["details"]["required_role"] == "MASTER_ADMIN"
    assert detail["error"]["details"]["actor_role"] == "OPERATOR"


@pytest.mark.unit
def test_role_rank_denies_read_only_for_master_admin() -> None:
    """READ_ONLY cannot satisfy MASTER_ADMIN minimum."""
    assert role_rank("READ_ONLY") < role_rank(Role.MASTER_ADMIN.name)


@pytest.mark.unit
def test_role_rank_allows_master_admin_for_operator() -> None:
    """MASTER_ADMIN satisfies OPERATOR minimum."""
    assert role_rank("MASTER_ADMIN") >= role_rank(Role.OPERATOR.name)


@pytest.mark.unit
def test_forbidden_raises_http_exception() -> None:
    """Forbidden helper produces HTTPException for route guards."""
    exc = forbidden_error(required_role="ANALYST", actor_role="READ_ONLY")
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 403
