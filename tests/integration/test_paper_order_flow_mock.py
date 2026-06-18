"""Integration E2E: paper order flow with a mocked broker handoff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from audit_service.chain import verify_range
from compliance_service.app import check_order_request
from compliance_service.engine import ComplianceEngine
from oms.app import create_app as create_oms_app
from oms.settings import Settings as OmsSettings
from risk_service.app import validate_order_request
from risk_service.validator import OrderRiskValidator
from zinc_proto import compliance_pb2, risk_pb2
from zinc_test._infra import _normalize_psycopg_dsn, _run_sql_file, app_dsn_from_admin

_ROOT = Path(__file__).resolve().parents[2]
_ADMIN_SEED_ORDERS = _ROOT / "services" / "admin_service" / "tests" / "sql" / "seed_orders.sql"

PENDING_ORDER_ID = "cc0e8400-e29b-41d4-a716-446655440001"


def _fetch_order_context(dsn: str) -> dict[str, object]:
    with psycopg.connect(_normalize_psycopg_dsn(dsn)) as conn:
        row = conn.execute(
            """
            SELECT o.id::text, o.portfolio_id::text, o.instrument_id,
                   i.symbol, o.side, o.qty, o.limit_price
              FROM theeyebeta.orders o
              JOIN theeyebeta.instruments i ON i.id = o.instrument_id
             WHERE o.id = %s
            """,
            (PENDING_ORDER_ID,),
        ).fetchone()
    assert row is not None
    return {
        "order_id": str(row[0]),
        "portfolio_id": str(row[1]),
        "instrument_id": int(row[2]),
        "symbol": str(row[3]),
        "side": str(row[4]),
        "qty": float(row[5]),
        "limit_price": float(row[6] or 100.0),
    }


def _audit_count(dsn: str, order_id: str) -> int:
    with psycopg.connect(_normalize_psycopg_dsn(dsn)) as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                  FROM theeyebeta.audit_log
                 WHERE entity_type = 'order'
                   AND entity_id = %s
                """,
                (order_id,),
            ).fetchone()[0],
        )


@pytest.mark.integration
async def test_paper_order_flow_risk_compliance_oms_audit(alembic_upgraded: str) -> None:
    """Submit a paper order through risk, compliance, OMS, and audit verification."""
    dsn = app_dsn_from_admin(alembic_upgraded)
    _run_sql_file(dsn, _ADMIN_SEED_ORDERS)
    order = _fetch_order_context(dsn)

    with patch.dict("os.environ", {"DATABASE_URL": dsn}, clear=False):
        risk_result = await validate_order_request(
            OrderRiskValidator(),
            risk_pb2.RiskCheckRequest(
                portfolio_id=str(order["portfolio_id"]),
                instrument_id=int(order["instrument_id"]),
                side=str(order["side"]),
                qty=float(order["qty"]),
                limit_price=float(order["limit_price"]),
                order_intent=str(order["side"]).upper(),
                sector="technology",
                cluster="tech",
            ),
        )
        assert risk_result.approved, risk_result.reason

        compliance_result = await check_order_request(
            ComplianceEngine(),
            compliance_pb2.ComplianceCheckRequest(
                order_id=str(order["order_id"]),
                portfolio_id=str(order["portfolio_id"]),
                instrument_id=int(order["instrument_id"]),
                symbol=str(order["symbol"]),
                side=str(order["side"]),
                qty=float(order["qty"]),
                limit_price=max(float(order["limit_price"]), 10000.0),
                market="US",
            ),
        )
        assert compliance_result.approved, compliance_result.reason

    before_audit = _audit_count(dsn, str(order["order_id"]))
    verify_from = datetime.now(tz=UTC) - timedelta(seconds=1)
    app = create_oms_app(
        OmsSettings(
            database_url=dsn,
            nats_url="nats://127.0.0.1:4222",
            redis_url="redis://127.0.0.1:6379/15",
        ),
    )

    with patch("oms.consumer.OmsEventConsumer.publish_approved", AsyncMock()) as publish_mock:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/oms/orders/{order['order_id']}/approve",
                json={"approved_by": "ci-integration"},
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "submitted"
    assert body["transitions"][-1]["status"] == "submitted"
    publish_mock.assert_awaited_once()

    after_audit = _audit_count(dsn, str(order["order_id"]))
    assert after_audit == before_audit + 1
    verified = await verify_range(
        dsn,
        from_ts=verify_from,
        to_ts=datetime.now(tz=UTC) + timedelta(seconds=1),
    )
    assert verified.status == "OK", verified.detail
