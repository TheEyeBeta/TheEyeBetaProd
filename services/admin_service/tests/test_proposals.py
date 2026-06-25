"""Integration tests for admin proposals API."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from httpx import AsyncClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

_conf_spec = importlib.util.spec_from_file_location(
    "admin_test_conftest",
    _TESTS_DIR / "conftest.py",
)
assert _conf_spec is not None and _conf_spec.loader is not None
_admin_conf = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(_admin_conf)
_normalize_psycopg_dsn = _admin_conf._normalize_psycopg_dsn

PENDING_STRATEGY_PROPOSAL = "ff111111-1111-1111-1111-111111111111"
PENDING_CONSTITUTION_PROPOSAL = "ff222222-2222-2222-2222-222222222222"
REJECTED_PROPOSAL = "ff333333-3333-3333-3333-333333333333"
STRATEGY_ID = "momentum-v1"

_CONFIRM = {"reason": "operator approval", "confirm": True}


def _confirm_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {**auth_headers, "X-Confirm": "true"}

_SEED_FILE = _TESTS_DIR / "sql" / "seed_proposals.sql"


def _audit_count(dsn: str, proposal_id: str, action: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)::int
              FROM theeyebeta.audit_log
             WHERE entity_id = %s AND action = %s
            """,
            (proposal_id, action),
        ).fetchone()
    return int(row[0]) if row else 0


def _proposal_status(dsn: str, proposal_id: str) -> str:
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            "SELECT status FROM theeyebeta.proposals WHERE id = %s",
            (proposal_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _reset_proposals(dsn: str) -> None:
    """Re-run the seed SQL after each test that mutates state."""
    with psycopg.connect(_normalize_psycopg_dsn(dsn), autocommit=True) as conn:
        conn.execute(
            """
            UPDATE theeyebeta.proposals
               SET status = CASE id::text
                              WHEN '"""  # noqa: ISC001
            + REJECTED_PROPOSAL
            + """' THEN 'rejected'
                              ELSE 'pending'
                            END,
                   reviewed_by = NULL,
                   reviewed_at = NULL,
                   review_notes = NULL,
                   validation_backtest_id = NULL
            """,
        )
        conn.execute(
            """
            DELETE FROM theeyebeta.backtest_runs
             WHERE config ? 'triggered_by_proposal'
            """,
        )
        conn.execute(
            """
            DELETE FROM theeyebeta.audit_log
             WHERE action IN ('approve.proposal', 'reject.proposal')
            """,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_happy(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/proposals returns seeded rows newest first."""
    client, _ = proposals_admin_client
    response = await client.get("/admin/proposals", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    ids = {row["id"] for row in body["proposals"]}
    assert PENDING_STRATEGY_PROPOSAL in ids
    assert PENDING_CONSTITUTION_PROPOSAL in ids
    assert REJECTED_PROPOSAL in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_filters(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """status / category filters narrow the result set."""
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals",
        params={"status": "pending", "category": "strategy_param"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["proposals"]) == 1
    assert body["proposals"][0]["id"] == PENDING_STRATEGY_PROPOSAL


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_invalid_status(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Unknown status filter returns 422."""
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals",
        params={"status": "unknown"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_proposal_happy(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """GET /admin/proposals/{id} returns the full payload."""
    client, _ = proposals_admin_client
    response = await client.get(
        f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == PENDING_STRATEGY_PROPOSAL
    assert body["category"] == "strategy_param"
    assert body["current_value"] == {"lookback": 20}
    assert body["proposed_value"] == {"lookback": 30}
    assert body["estimated_impact"] == {"sharpe_delta": 0.12}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_proposal_not_found(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Unknown id returns 404."""
    client, _ = proposals_admin_client
    response = await client.get(
        "/admin/proposals/00000000-0000-0000-0000-000000000099",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_with_backtest_publishes_nats(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Approve creates backtest_runs row, publishes NATS, audits."""
    _reset_proposals(proposals_integration_dsn)
    client, nats = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}/approve",
        headers=_confirm_headers(auth_headers),
        json={
            **_CONFIRM,
            "review_notes": "looks compelling",
            "strategy_id": STRATEGY_ID,
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "universe": "sp500",
            "git_sha": "abc123",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == "admin-api:test-operator"
    assert body["validation_backtest_id"] is not None
    backtest_id = body["validation_backtest_id"]

    assert _proposal_status(proposals_integration_dsn, PENDING_STRATEGY_PROPOSAL) == "approved"
    assert (
        _audit_count(
            proposals_integration_dsn,
            PENDING_STRATEGY_PROPOSAL,
            "approve.proposal",
        )
        == 1
    )

    # NATS event published.
    subjects = [s for s, _ in nats.published]
    assert "backtests.requested" in subjects
    payload = next(p for s, p in nats.published if s == "backtests.requested")
    event = json.loads(payload.decode())
    assert event["proposal_id"] == PENDING_STRATEGY_PROPOSAL
    assert event["backtest_run_id"] == backtest_id
    assert event["strategy_id"] == STRATEGY_ID

    dsn = _normalize_psycopg_dsn(proposals_integration_dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT status, strategy_id FROM theeyebeta.backtest_runs WHERE id = %s",
            (backtest_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "running"
    assert row[1] == STRATEGY_ID


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_skip_backtest(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """skip_backtest=true approves without inserting a backtest row."""
    _reset_proposals(proposals_integration_dsn)
    client, nats = proposals_admin_client
    before = len(nats.published)

    response = await client.post(
        f"/admin/proposals/{PENDING_CONSTITUTION_PROPOSAL}/approve",
        headers=_confirm_headers(auth_headers),
        json={**_CONFIRM, "skip_backtest": True, "review_notes": "n/a — non-strategy"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["validation_backtest_id"] is None

    # No new NATS messages.
    assert len(nats.published) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_missing_backtest_fields(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Without skip_backtest, missing strategy/dates yields 422."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}/approve",
        headers=_confirm_headers(auth_headers),
        json={**_CONFIRM, "review_notes": "missing fields"},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_unknown_strategy(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Unknown strategy_id surfaces as 422."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}/approve",
        headers=_confirm_headers(auth_headers),
        json={
            **_CONFIRM,
            "strategy_id": "does-not-exist",
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "universe": "sp500",
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_conflict(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Approving an already-rejected proposal returns 409."""
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{REJECTED_PROPOSAL}/approve",
        headers=_confirm_headers(auth_headers),
        json={**_CONFIRM, "skip_backtest": True},
    )
    assert response.status_code == 409


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approve_not_found(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Approving a missing proposal returns 404."""
    client, _ = proposals_admin_client
    response = await client.post(
        "/admin/proposals/00000000-0000-0000-0000-000000000099/approve",
        headers=_confirm_headers(auth_headers),
        json={**_CONFIRM, "skip_backtest": True},
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_happy(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """POST reject transitions to rejected and audits the action."""
    _reset_proposals(proposals_integration_dsn)
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{PENDING_CONSTITUTION_PROPOSAL}/reject",
        headers=auth_headers,
        json={"review_notes": "out of scope for this quarter"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["review_notes"] == "out of scope for this quarter"
    assert body["reviewed_by"] == "admin-api:test-operator"
    assert (
        _audit_count(
            proposals_integration_dsn,
            PENDING_CONSTITUTION_PROPOSAL,
            "reject.proposal",
        )
        == 1
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_validation(
    proposals_admin_client: tuple[AsyncClient, object],
    auth_headers: dict[str, str],
) -> None:
    """Empty review_notes fails Pydantic validation with 422."""
    client, _ = proposals_admin_client
    response = await client.post(
        f"/admin/proposals/{PENDING_CONSTITUTION_PROPOSAL}/reject",
        headers=auth_headers,
        json={"review_notes": ""},
    )
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_proposals_auth_required(proposals_integration_dsn: str) -> None:
    """All proposal endpoints reject unauthenticated requests."""
    from httpx import ASGITransport  # noqa: PLC0415
    from main import create_app  # noqa: PLC0415
    from settings import Settings, get_settings  # noqa: PLC0415

    _close = _admin_conf._close_test_resources
    _init = _admin_conf._init_test_resources

    get_settings.cache_clear()
    settings = Settings(database_url=proposals_integration_dsn)
    with (
        patch("deps.init_resources", _init),
        patch("deps.close_resources", _close),
    ):
        app = create_app(settings)
        transport = ASGITransport(app=app, lifespan="on")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/admin/proposals")).status_code == 401
            assert (
                await client.get(f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}")
            ).status_code == 401
            assert (
                await client.post(
                    f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}/approve",
                    json={"skip_backtest": True},
                )
            ).status_code == 401
            assert (
                await client.post(
                    f"/admin/proposals/{PENDING_STRATEGY_PROPOSAL}/reject",
                    json={"review_notes": "no"},
                )
            ).status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reject_rate_limit(
    proposals_admin_client: tuple[AsyncClient, object],
    proposals_integration_dsn: str,
    auth_headers: dict[str, str],
) -> None:
    """Burst reject calls eventually return 429 (20/min write limit)."""
    client, _ = proposals_admin_client
    statuses: list[int] = []
    for _ in range(22):
        _reset_proposals(proposals_integration_dsn)
        resp = await client.post(
            f"/admin/proposals/{PENDING_CONSTITUTION_PROPOSAL}/reject",
            headers=auth_headers,
            json={"review_notes": "burst"},
        )
        statuses.append(resp.status_code)
    assert 200 in statuses
    assert 429 in statuses
