"""Integration test: macro-lead run against fixture snapshot (testcontainers + mocked LLM)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import nats
import psycopg
import pytest
from agent_runtime.runner import AgentRunner
from minio import Minio
from prometheus_client import REGISTRY

SNAPSHOT_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
TRADE_DATE = date(2025, 1, 15)
BLOB_KEY = f"packaged/US/{TRADE_DATE.year:04d}/{TRADE_DATE.month:02d}/{TRADE_DATE.isoformat()}.json"
LLM_PROXY = "http://llm-gateway.test:4000"
AGENT_ID = "macro-lead"
NATS_SUBJECT = f"agents.decisions.{AGENT_ID}"

_VALID_OUTPUT: dict[str, Any] = {
    "market_stance": "neutral",
    "regime_call": "ranging",
    "decisions": [
        {
            "instrument_symbol": "AAPL",
            "decision": "HOLD",
            "confidence": 0.65,
            "horizon_days": 10,
            "key_drivers": [
                "macro.us.dgs10 elevated",
                "technicals.AAPL.rsi14 neutral",
            ],
            "rationale": (
                "technicals.AAPL.rsi14 at 55 and macro.us.dgs10 at 4.25 "
                "suggest range-bound conditions."
            ),
        },
    ],
}


def _completion_payload(content: str | None = None) -> dict[str, Any]:
    body = json.dumps(_VALID_OUTPUT) if content is None else content
    return {
        "id": "chatcmpl-integration",
        "object": "chat.completion",
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": body},
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "total_tokens": 165,
        },
    }


def _snapshot_payload(instrument_id: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "market": "US",
        "snapshot_id": str(SNAPSHOT_ID),
        "as_of": "2025-01-15T23:59:59+00:00",
        "universe": [
            {
                "symbol": "AAPL",
                "instrument_id": instrument_id,
                "sector": "Technology",
                "industry": None,
            },
        ],
        "prices": {
            "AAPL": {
                "open": 100.0,
                "high": 110.0,
                "low": 95.0,
                "close": 105.0,
                "adj_close": 105.0,
                "volume": 1_000_000,
            },
        },
        "technicals": {
            "AAPL": {
                "atr14": 1.5,
                "adx14": 22.0,
                "rsi14": 55.0,
                "zscore20": 0.1,
                "bb_upper20_2": 110.0,
                "bb_lower20_2": 90.0,
            },
        },
        "macro": {"us.dgs10": 4.25},
        "news_summary": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "headline": "Test",
                "tickers": ["AAPL"],
                "published_at": datetime(2025, 1, 15, 12, 0, tzinfo=UTC).isoformat(),
            },
        ],
    }


async def _seed_packaged_snapshot(
    dsn: str,
    *,
    minio_endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    instrument_id: int,
) -> None:
    """Upload snapshot JSON to MinIO and insert catalog row."""
    payload = _snapshot_payload(instrument_id)
    raw = json.dumps(payload).encode()
    digest = hashlib.sha256(raw).digest()
    blob_uri = f"s3://{bucket}/{BLOB_KEY}"

    client = Minio(
        minio_endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(
        bucket,
        BLOB_KEY,
        data=io.BytesIO(raw),
        length=len(raw),
        content_type="application/json",
    )

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            INSERT INTO theeyebeta.data_snapshots_packaged
                (snapshot_id, market, trade_date, schema_version, blob_uri,
                 blob_sha256, universe_size)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market, trade_date, schema_version) DO UPDATE SET
                snapshot_id = EXCLUDED.snapshot_id,
                blob_uri = EXCLUDED.blob_uri,
                blob_sha256 = EXCLUDED.blob_sha256,
                universe_size = EXCLUDED.universe_size,
                packaged_at = now()
            """,
            (
                SNAPSHOT_ID,
                "US",
                TRADE_DATE,
                1,
                blob_uri,
                digest,
                1,
            ),
        )
        await conn.commit()


def _counter_value(agent_id: str, status: str) -> float:
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name.endswith("_created"):
                continue
            if (
                sample.labels.get("agent_id") == agent_id
                and sample.labels.get("status") == status
                and "agent_runs" in sample.name
            ):
                return float(sample.value)
    return 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_macro_lead_run_guard_runtime_contract(
    integration_env,
    httpx_mock,
) -> None:  # noqa: ANN001
    """Run macro-lead: DB rows, NATS event, model_runs, and Prometheus metrics."""
    httpx_mock.add_response(
        url=f"{LLM_PROXY}/v1/chat/completions",
        json=_completion_payload(),
        headers={"x-litellm-response-cost": "0.002"},
    )

    dsn = integration_env.ingest_database_url
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT i.id
              FROM theeyebeta.instruments i
              JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
             WHERE i.symbol = 'AAPL' AND e.code = 'XNAS'
            """,
        )
        instrument_row = await cur.fetchone()
    assert instrument_row is not None

    await _seed_packaged_snapshot(
        dsn,
        minio_endpoint=integration_env.minio_endpoint,
        access_key=integration_env.minio_access_key,
        secret_key=integration_env.minio_secret_key,
        bucket=integration_env.minio_bucket,
        instrument_id=int(instrument_row[0]),
    )

    received: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()

    async def on_message(msg: nats.aio.msg.Msg) -> None:
        await received.put((msg.subject, msg.data))

    subscriber = await nats.connect(integration_env.nats_url)
    sub = await subscriber.subscribe(NATS_SUBJECT, cb=on_message)

    try:
        summary = await AgentRunner().run(AGENT_ID, SNAPSHOT_ID)
    finally:
        await sub.unsubscribe()
        await subscriber.close()

    assert summary["run_id"]
    assert summary["market_stance"] == "neutral"

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        run_row = await (
            await conn.execute(
                """
                SELECT status, total_input_tokens, total_output_tokens
                  FROM theeyebeta.agent_runs
                 WHERE id = %s
                """,
                (UUID(summary["run_id"]),),
            )
        ).fetchone()
        assert run_row is not None
        assert run_row[0] == "succeeded"
        assert run_row[1] == 120
        assert run_row[2] == 45

        decisions = await (
            await conn.execute(
                """
                SELECT confidence, rationale
                  FROM theeyebeta.agent_decisions
                 WHERE run_id = %s
                """,
                (UUID(summary["run_id"]),),
            )
        ).fetchall()
        assert len(decisions) >= 1
        for confidence, rationale in decisions:
            assert 0.0 <= float(confidence) <= 1.0
            assert rationale and str(rationale).strip()

        model_run_count = await (
            await conn.execute(
                "SELECT COUNT(*) FROM theeyebeta.model_runs WHERE run_id = %s",
                (UUID(summary["run_id"]),),
            )
        ).fetchone()
        assert model_run_count is not None
        assert int(model_run_count[0]) >= 1

    subject, payload = await asyncio.wait_for(received.get(), timeout=10.0)
    assert subject == NATS_SUBJECT
    event = json.loads(payload.decode())
    assert event["agent_id"] == AGENT_ID
    assert event["run_id"] == summary["run_id"]
    assert event["decision_ids"]

    assert _counter_value(AGENT_ID, "succeeded") >= 1.0
