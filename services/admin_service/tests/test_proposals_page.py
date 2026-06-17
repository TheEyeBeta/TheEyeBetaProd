"""Integration tests for ``/admin/proposals`` (page + fragments).

Reuses the existing ``seed_proposals.sql`` fixture (2 pending, 1 rejected;
the approved tab is asserted to be empty unless a test approves one).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest_proposalspage",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)
_normalize_psycopg_dsn = _admin_conf._normalize_psycopg_dsn


_PENDING_1 = "ff111111-1111-1111-1111-111111111111"
_PENDING_2 = "ff222222-2222-2222-2222-222222222222"
_REJECTED = "ff333333-3333-3333-3333-333333333333"


def _proposal_status(dsn: str, proposal_id: str) -> str:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            "SELECT status FROM theeyebeta.proposals WHERE id = %s",
            (proposal_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _backtest_for_proposal(dsn: str, proposal_id: str) -> str | None:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            "SELECT validation_backtest_id FROM theeyebeta.proposals WHERE id = %s",
            (proposal_id,),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def _audit_count(dsn: str, action: str, entity_id: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE action = %s AND entity_id = %s
            """,
            (action, entity_id),
        ).fetchone()
    return int(row[0]) if row else 0


def _reset_proposals(dsn: str) -> None:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(
            """
            UPDATE theeyebeta.proposals
               SET status = CASE id
                              WHEN %s::uuid THEN 'pending'
                              WHEN %s::uuid THEN 'pending'
                              WHEN %s::uuid THEN 'rejected'
                            END,
                   reviewed_by = NULL,
                   reviewed_at = NULL,
                   review_notes = NULL,
                   validation_backtest_id = NULL
             WHERE id IN (%s::uuid, %s::uuid, %s::uuid)
            """,
            (_PENDING_1, _PENDING_2, _REJECTED, _PENDING_1, _PENDING_2, _REJECTED),
        )
        conn.execute(
            "DELETE FROM theeyebeta.backtest_runs WHERE config ->> 'kind' = 'validation'",
        )
        conn.execute(
            """
            DELETE FROM theeyebeta.audit_log
             WHERE entity_type = 'proposal'
               AND entity_id IN (%s, %s, %s)
            """,
            (_PENDING_1, _PENDING_2, _REJECTED),
        )


# ---------------------------------------------------------------- Page render


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_page_renders_tabs_and_pending_cards(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Initial GET renders the three tab buttons and pending cards by default."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get("/admin/proposals", headers=auth_headers)
    assert response.status_code == 200
    body = response.text
    assert 'data-page="proposals"' in body
    assert 'data-test-id="proposals-tab-pending"' in body
    assert 'data-test-id="proposals-tab-approved"' in body
    assert 'data-test-id="proposals-tab-rejected"' in body
    # Two pending cards from the seed.
    assert body.count('data-test-id="proposal-card"') == 2
    # Markdown and highlight.js CDN scripts.
    assert "markdown-it" in body
    assert "highlight.min.js" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_tab_fragment_for_rejected(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Switching to the Rejected tab returns 1 card (the seeded rejected row)."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals/fragments/tab?status=rejected",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "<html" not in body.lower()
    assert 'data-active-status="rejected"' in body
    assert 'data-row-count="1"' in body
    assert _REJECTED in body
    # The pending IDs should not appear.
    assert _PENDING_1 not in body
    assert _PENDING_2 not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_tab_fragment_approved_empty(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Approved tab is empty in the default seed."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals/fragments/tab?status=approved",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-row-count="0"' in body
    assert 'data-empty="true"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_tab_fragment_rejects_invalid_status(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
) -> None:
    """Unknown ``status`` query param → 422 (matches the tab key allow-list)."""
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals/fragments/tab?status=applied",
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_tab_fragment_filters_by_category(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Category filter narrows the pending tab to a single row."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals/fragments/tab",
        params={"status": "pending", "category": "strategy_param"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-row-count="1"' in body
    assert _PENDING_1 in body
    assert _PENDING_2 not in body


# ---------------------------------------------------------------- Approve flow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_approve_modal_prefills_strategy_id(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Approve modal pre-fills ``strategy_id`` for strategy_param proposals."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get(
        f"/admin/proposals/fragments/{_PENDING_1}/approve-modal",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="proposal-approve-modal"' in body
    assert 'name="strategy_id"' in body
    assert 'value="momentum-v1"' in body
    assert 'name="start_date"' in body
    assert 'name="end_date"' in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_approve_queues_backtest_and_publishes_event(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Submitting the approve modal triggers DB + NATS + flash + refreshed card."""
    _reset_proposals(proposals_integration_dsn)
    client, recorder = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/fragments/{_PENDING_1}/approve",
        headers=auth_headers,
        data={
            "review_notes": "Looks reasonable.",
            "strategy_id": "momentum-v1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "universe": "sp500",
        },
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="proposal-card"' in body
    assert 'data-proposal-status="approved"' in body
    assert response.headers.get("HX-Trigger", "").startswith("{")
    assert "Proposal approved" in response.headers["HX-Trigger"]
    # DB state.
    assert _proposal_status(proposals_integration_dsn, _PENDING_1) == "approved"
    assert _backtest_for_proposal(proposals_integration_dsn, _PENDING_1) is not None
    # Audit + NATS.
    assert _audit_count(proposals_integration_dsn, "approve.proposal", _PENDING_1) == 1
    subjects = [evt[0] for evt in getattr(recorder, "published", [])]
    assert "backtests.requested" in subjects
    _reset_proposals(proposals_integration_dsn)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_approve_skip_backtest(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """``skip_backtest=true`` approves without queuing a backtest."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/fragments/{_PENDING_2}/approve",
        headers=auth_headers,
        data={
            "skip_backtest": "true",
            "review_notes": "Constitution change — no backtest needed.",
        },
    )
    assert response.status_code == 200
    assert _proposal_status(proposals_integration_dsn, _PENDING_2) == "approved"
    assert _backtest_for_proposal(proposals_integration_dsn, _PENDING_2) is None
    _reset_proposals(proposals_integration_dsn)


# ---------------------------------------------------------------- Reject flow


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_reject_modal_renders(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Reject modal is content-typed HTML with a required notes field."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.get(
        f"/admin/proposals/fragments/{_PENDING_1}/reject-modal",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="proposal-reject-modal"' in body
    assert 'name="review_notes"' in body
    assert "required" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_reject_updates_status_and_audits(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Submitting the reject modal transitions to rejected + writes audit row."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/fragments/{_PENDING_2}/reject",
        headers=auth_headers,
        data={"review_notes": "Not in scope this quarter."},
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-proposal-status="rejected"' in body
    assert response.headers.get("HX-Trigger", "").startswith("{")
    assert "Proposal rejected" in response.headers["HX-Trigger"]
    assert _proposal_status(proposals_integration_dsn, _PENDING_2) == "rejected"
    assert _audit_count(proposals_integration_dsn, "reject.proposal", _PENDING_2) == 1
    _reset_proposals(proposals_integration_dsn)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_reject_blank_notes_returns_422(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """Empty ``review_notes`` is rejected by FastAPI form validation."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/fragments/{_PENDING_1}/reject",
        headers=auth_headers,
        data={"review_notes": ""},
    )
    assert response.status_code == 422
    assert _proposal_status(proposals_integration_dsn, _PENDING_1) == "pending"


# ---------------------------------------------------------------- Backtest poll


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposal_backtest_status_poll(
    proposals_admin_client: tuple[AsyncClient, Any],
    auth_headers: dict[str, str],
    proposals_integration_dsn: str,
) -> None:
    """After approval, the backtest-status poll returns the run state."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    # Approve to create the backtest.
    await client.post(
        f"/admin/proposals/fragments/{_PENDING_1}/approve",
        headers=auth_headers,
        data={
            "strategy_id": "momentum-v1",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "universe": "sp500",
        },
    )
    response = await client.get(
        f"/admin/proposals/fragments/{_PENDING_1}/backtest-status",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.text
    assert 'data-test-id="proposal-backtest-status"' in body
    # ``running`` is what ``_create_validation_backtest`` inserts.
    assert 'data-status="running"' in body
    assert 'data-polling="true"' in body
    _reset_proposals(proposals_integration_dsn)


# ---------------------------------------------------------------- Auth gate


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_page_requires_auth(
    proposals_integration_dsn: str,
) -> None:
    """All proposals routes are JWT-gated."""
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    from services.admin_service.tests.conftest import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _close_test_resources,
        _init_test_resources,
    )

    get_settings.cache_clear()
    settings = Settings(database_url=proposals_integration_dsn)
    with (
        patch("deps.init_resources", _init_test_resources),
        patch("deps.close_resources", _close_test_resources),
    ):
        app = create_app(settings=settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            page = await anon.get("/admin/proposals")
            tab = await anon.get("/admin/proposals/fragments/tab")
            approve_modal = await anon.get(f"/admin/proposals/fragments/{_PENDING_1}/approve-modal")
            approve = await anon.post(
                f"/admin/proposals/fragments/{_PENDING_1}/approve",
                data={"skip_backtest": "true"},
            )
            reject_modal = await anon.get(f"/admin/proposals/fragments/{_PENDING_2}/reject-modal")
            reject = await anon.post(
                f"/admin/proposals/fragments/{_PENDING_2}/reject",
                data={"review_notes": "no"},
            )
            poll = await anon.get(f"/admin/proposals/fragments/{_PENDING_1}/backtest-status")
    assert page.status_code == 401
    assert tab.status_code == 401
    assert approve_modal.status_code == 401
    assert approve.status_code == 401
    assert reject_modal.status_code == 401
    assert reject.status_code == 401
    assert poll.status_code == 401
