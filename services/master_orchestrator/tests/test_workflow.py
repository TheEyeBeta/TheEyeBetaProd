"""Acceptance: market-trio workflow, idempotency, and integration tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import nats
import psycopg
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS = Path(__file__).resolve().parent
for _p in (_SRC, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from conftest import (  # noqa: E402
    PORTFOLIO_ID,
    SNAPSHOT_ID,
    TRADE_DATE,
    _agent_result,
)

from master_orchestrator.consumer import SnapshotEventConsumer  # noqa: E402
from master_orchestrator.settings import Settings  # noqa: E402
from master_orchestrator.workflow import MarketTrioWorkflow  # noqa: E402


def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("+asyncpg", "").replace("+psycopg", "")


async def _count_pending_orders(dsn: str) -> int:
    async with await psycopg.AsyncConnection.connect(_normalize_dsn(dsn)) as conn:
        cur = await conn.execute(
            """
            SELECT COUNT(*) FROM theeyebeta.orders
             WHERE portfolio_id = %s AND status = 'pending_approval'
            """,
            (PORTFOLIO_ID,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _instrument_id_for_symbol(dsn: str, symbol: str = "AAPL") -> int:
    async with await psycopg.AsyncConnection.connect(_normalize_dsn(dsn)) as conn:
        cur = await conn.execute(
            "SELECT id FROM theeyebeta.instruments WHERE symbol = %s LIMIT 1",
            (symbol,),
        )
        row = await cur.fetchone()
    if row is None:
        msg = f"instrument {symbol} not seeded"
        raise RuntimeError(msg)
    return int(row[0])


def _consensus_buy_trio(instrument_id: int) -> list:
    return [
        _agent_result("macro-lead", decision="BUY", instrument_id=instrument_id),
        _agent_result("news-sentiment", decision="BUY", instrument_id=instrument_id),
        _agent_result("technical-analyst", decision="BUY", instrument_id=instrument_id),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workflow_produces_one_pending_order(
    settings: Settings,
    aligned_trio: list,
    sample_ticket,
) -> None:
    """Full workflow inserts exactly one orders row and publishes NATS event."""
    order_id = uuid4()
    trio = aligned_trio

    with (
        patch.object(
            MarketTrioWorkflow,
            "_spawn_agents",
            AsyncMock(return_value=trio),
        ),
        patch(
            "master_orchestrator.workflow.TicketSynthesizer.synthesize",
            AsyncMock(return_value=sample_ticket),
        ),
        patch(
            "master_orchestrator.workflow.resolve_portfolio_id",
            AsyncMock(return_value=PORTFOLIO_ID),
        ),
        patch(
            "master_orchestrator.workflow.insert_pending_order",
            AsyncMock(return_value=order_id),
        ) as mock_insert,
        patch(
            "master_orchestrator.workflow.publish_order_proposed",
            AsyncMock(),
        ) as mock_publish,
    ):
        workflow = MarketTrioWorkflow(settings)
        result = await workflow.run("US", SNAPSHOT_ID)

    assert result.order_id == str(order_id)
    assert result.ticket is not None
    assert result.ticket.side == "buy"
    assert result.debated is False
    assert result.outcome == "consensus"
    mock_insert.assert_awaited_once()
    mock_publish.assert_awaited_once()
    insert_kwargs = mock_insert.await_args.kwargs
    assert insert_kwargs["portfolio_id"] == PORTFOLIO_ID
    assert insert_kwargs["ticket"] == sample_ticket


@pytest.mark.unit
@pytest.mark.asyncio
async def test_workflow_triggers_debate_on_disagreement(
    settings: Settings,
    disagreeing_trio: list,
    sample_ticket,
) -> None:
    """BUY vs SELL triggers debate before synthesis."""
    from master_orchestrator.models import DebateTranscript

    resolved = [
        _agent_result("macro-lead", decision="BUY"),
        _agent_result("news-sentiment", decision="BUY"),
        _agent_result("technical-analyst", decision="BUY"),
    ]
    transcript = DebateTranscript(final_results=resolved)

    with (
        patch.object(
            MarketTrioWorkflow,
            "_spawn_agents",
            AsyncMock(return_value=disagreeing_trio),
        ),
        patch(
            "master_orchestrator.workflow.DebateRound.run",
            AsyncMock(return_value=transcript),
        ) as mock_debate,
        patch(
            "master_orchestrator.workflow.TicketSynthesizer.synthesize",
            AsyncMock(return_value=sample_ticket),
        ),
        patch(
            "master_orchestrator.workflow.resolve_portfolio_id",
            AsyncMock(return_value=PORTFOLIO_ID),
        ),
        patch(
            "master_orchestrator.workflow.insert_pending_order",
            AsyncMock(return_value=uuid4()),
        ),
        patch("master_orchestrator.workflow.publish_order_proposed", AsyncMock()),
    ):
        result = await MarketTrioWorkflow(settings).run("US", SNAPSHOT_ID)

    mock_debate.assert_awaited_once()
    assert result.debated is True
    assert result.outcome == "debate"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idempotency_skips_duplicate_trio(settings: Settings, sample_ticket) -> None:
    """Re-run with the same market/date returns skipped without a second order."""
    order_id = uuid4()
    trio = [
        _agent_result("macro-lead", decision="BUY"),
        _agent_result("news-sentiment", decision="BUY"),
        _agent_result("technical-analyst", decision="BUY"),
    ]
    mock_lock = AsyncMock()
    mock_lock.try_acquire = AsyncMock(side_effect=[True, False])
    mock_lock.mark_complete = AsyncMock()
    mock_lock.release = AsyncMock()

    with (
        patch.object(MarketTrioWorkflow, "_spawn_agents", AsyncMock(return_value=trio)),
        patch(
            "master_orchestrator.workflow.TicketSynthesizer.synthesize",
            AsyncMock(return_value=sample_ticket),
        ),
        patch(
            "master_orchestrator.workflow.resolve_portfolio_id",
            AsyncMock(return_value=PORTFOLIO_ID),
        ),
        patch(
            "master_orchestrator.workflow.insert_pending_order",
            AsyncMock(return_value=order_id),
        ) as mock_insert,
        patch("master_orchestrator.workflow.publish_order_proposed", AsyncMock()),
    ):
        workflow = MarketTrioWorkflow(settings, idempotency=mock_lock)
        first = await workflow.run("US", SNAPSHOT_ID, trade_date=TRADE_DATE)
        second = await workflow.run("US", SNAPSHOT_ID, trade_date=TRADE_DATE)

    assert first.skipped is False
    assert first.order_id == str(order_id)
    assert second.skipped is True
    assert second.outcome == "skipped"
    assert second.order_id is None
    mock_insert.assert_awaited_once()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_nats_event_produces_one_pending_order(integration_env) -> None:
    """Publish snapshots.packaged event; assert one pending_approval order."""
    dsn = integration_env.ingest_database_url
    instrument_id = await _instrument_id_for_symbol(dsn)
    trio = _consensus_buy_trio(instrument_id)
    settings = Settings(
        database_url=dsn,
        nats_url=integration_env.nats_url,
        redis_url=integration_env.redis_url,
        default_portfolio_id=str(PORTFOLIO_ID),
        agent_runtime_url="http://agent-runtime.test:8004",
        llm_virtual_key="",
    )

    payload = {
        "market": "US",
        "date": TRADE_DATE,
        "snapshot_id": str(SNAPSHOT_ID),
        "blob_uri": "s3://test/snapshot.json",
        "schema_version": 1,
    }

    before = await _count_pending_orders(dsn)

    with (
        patch(
            "master_orchestrator.clients.AgentRuntimeClient.run_agent",
            AsyncMock(side_effect=trio),
        ),
        patch("master_orchestrator.db.publish_order_proposed", AsyncMock()),
    ):
        consumer = SnapshotEventConsumer(settings)
        await consumer.start()
        try:
            nc = await nats.connect(integration_env.nats_url)
            await nc.publish(
                f"snapshots.packaged.US.{TRADE_DATE}",
                json.dumps(payload).encode(),
            )
            await nc.close()
            await asyncio.sleep(2.0)
            if consumer._tasks:
                await asyncio.gather(*consumer._tasks, return_exceptions=True)
        finally:
            await consumer.stop()

    assert await _count_pending_orders(dsn) - before == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_republish_same_event_no_second_order(integration_env) -> None:
    """Re-publishing the same packaged snapshot event does not create a second order."""
    dsn = integration_env.ingest_database_url
    instrument_id = await _instrument_id_for_symbol(dsn)
    republish_date = "2025-01-16"
    settings = Settings(
        database_url=dsn,
        nats_url=integration_env.nats_url,
        redis_url=integration_env.redis_url,
        default_portfolio_id=str(PORTFOLIO_ID),
        agent_runtime_url="http://agent-runtime.test:8004",
        llm_virtual_key="",
    )
    payload = {
        "market": "US",
        "date": republish_date,
        "snapshot_id": str(SNAPSHOT_ID),
        "blob_uri": "s3://test/snapshot.json",
        "schema_version": 1,
    }

    async def _mock_run_agent(agent_id: str, *_args, **_kwargs):
        return _agent_result(agent_id, decision="BUY", instrument_id=instrument_id)

    async def _publish_once(consumer: SnapshotEventConsumer) -> None:
        nc = await nats.connect(integration_env.nats_url)
        await nc.publish(
            f"snapshots.packaged.US.{republish_date}",
            json.dumps(payload).encode(),
        )
        await nc.close()
        await asyncio.sleep(2.0)
        if consumer._tasks:
            await asyncio.gather(*consumer._tasks, return_exceptions=True)

    before = await _count_pending_orders(dsn)

    with (
        patch(
            "master_orchestrator.clients.AgentRuntimeClient.run_agent",
            AsyncMock(side_effect=_mock_run_agent),
        ),
        patch("master_orchestrator.db.publish_order_proposed", AsyncMock()),
    ):
        consumer = SnapshotEventConsumer(settings)
        await consumer.start()
        try:
            await _publish_once(consumer)
            mid = await _count_pending_orders(dsn)
            await _publish_once(consumer)
            after = await _count_pending_orders(dsn)
        finally:
            await consumer.stop()

    assert mid - before == 1
    assert after - before == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debate_triggered_when_agents_disagree(integration_env) -> None:
    """Integration path runs debate when initial trio disagrees."""
    dsn = integration_env.ingest_database_url
    instrument_id = await _instrument_id_for_symbol(dsn)
    settings = Settings(
        database_url=dsn,
        nats_url=integration_env.nats_url,
        redis_url=integration_env.redis_url,
        default_portfolio_id=str(PORTFOLIO_ID),
        agent_runtime_url="http://agent-runtime.test:8004",
        llm_virtual_key="",
    )

    async def _mock_run_agent(agent_id: str, *_args, kind: str = "run", **_kwargs):
        if kind == "rebuttal":
            return _agent_result(agent_id, decision="BUY", instrument_id=instrument_id)
        decisions = {
            "macro-lead": "BUY",
            "news-sentiment": "HOLD",
            "technical-analyst": "SELL",
        }
        return _agent_result(
            agent_id,
            decision=decisions.get(agent_id, "HOLD"),
            instrument_id=instrument_id,
        )

    workflow = MarketTrioWorkflow(settings)
    with (
        patch(
            "master_orchestrator.clients.AgentRuntimeClient.run_agent",
            AsyncMock(side_effect=_mock_run_agent),
        ),
        patch("master_orchestrator.workflow.publish_order_proposed", AsyncMock()),
    ):
        result = await workflow.run(
            "US",
            SNAPSHOT_ID,
            trade_date="2025-01-17",
        )

    assert result.debated is True
    assert result.outcome == "debate"
    assert result.transcript is not None
    assert len(result.transcript.rounds) >= 1
    assert result.order_id is not None
