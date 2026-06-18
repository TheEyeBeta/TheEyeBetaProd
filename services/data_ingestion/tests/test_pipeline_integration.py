"""End-to-end ingestion pipeline test with testcontainers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from unittest.mock import patch

import asyncpg
import nats
import pytest
from data_ingestion.pipeline import IngestionPipeline
from minio import Minio

from zinc_schemas.ingestion import PriceDailyRecord


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_run_us_market_end_to_end(integration_env) -> None:  # noqa: ANN001
    """Full pipeline: Postgres rows, MinIO Parquet, data_snapshots, and NATS event."""
    target = date(2025, 1, 15)
    market = "US"
    subject = f"data.snapshots.{market}.{target.isoformat()}"

    pool = await asyncpg.create_pool(integration_env.ingest_database_url, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        instrument_id = await conn.fetchval("""
            SELECT i.id
            FROM theeyebeta.instruments i
            JOIN theeyebeta.exchanges e ON e.id = i.exchange_id
            WHERE i.symbol = 'AAPL' AND e.code = 'XNAS'
            """)
    await pool.close()
    assert instrument_id is not None

    observed = datetime(2025, 1, 15, tzinfo=UTC)
    fixture_bar = PriceDailyRecord(
        source="yfinance",
        observed_at=observed,
        instrument_id=int(instrument_id),
        symbol="AAPL",
        exchange_code="XNAS",
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
        adj_close=105.0,
        volume=1_000_000,
    )

    async def mock_fetch(adapter_name: str, _target_date: date) -> list:
        if adapter_name == "yfinance":
            return [fixture_bar]
        return []

    received: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()

    async def on_message(msg: nats.aio.msg.Msg) -> None:
        await received.put((msg.subject, msg.data))

    subscriber = await nats.connect(integration_env.nats_url)
    sub = await subscriber.subscribe(subject, cb=on_message)

    try:
        with patch("data_ingestion.pipeline._fetch_adapter_records", side_effect=mock_fetch):
            summary = await IngestionPipeline().run(
                target,
                adapter_names=["yfinance", "fred", "alpaca_data", "cn_proxy", "news"],
            )

        assert summary["written"]["prices_daily"] >= 1
        assert market in summary["snapshots"]

        pool = await asyncpg.create_pool(
            integration_env.ingest_database_url,
            min_size=1,
            max_size=2,
        )
        async with pool.acquire() as conn:
            price_count = await conn.fetchval(
                """
                SELECT count(*)::int
                FROM theeyebeta.prices_daily
                WHERE instrument_id = $1
                  AND ts::date = $2
                """,
                instrument_id,
                target,
            )
            snapshot = await conn.fetchrow(
                """
                SELECT market, trade_date, blob_uri, universe_size
                FROM theeyebeta.data_snapshots
                WHERE market = $1 AND trade_date = $2
                """,
                market,
                target,
            )
        await pool.close()

        assert price_count == 1
        assert snapshot is not None
        assert snapshot["universe_size"] == 1

        minio_client = Minio(
            integration_env.minio_endpoint,
            access_key=integration_env.minio_access_key,
            secret_key=integration_env.minio_secret_key,
            secure=False,
        )
        object_key = f"{market}/{target.year:04d}/{target.month:02d}/{target.isoformat()}.parquet"
        stat = minio_client.stat_object(integration_env.minio_bucket, object_key)
        assert stat.size > 0

        msg_subject, msg_data = await asyncio.wait_for(received.get(), timeout=5.0)
        assert msg_subject == subject
        payload = json.loads(msg_data.decode())
        assert payload["market"] == market
        assert payload["date"] == str(target)
        assert payload["blob_uri"].startswith(f"s3://{integration_env.minio_bucket}/")
        assert payload["row_count"] == 1
    finally:
        await sub.unsubscribe()
        await subscriber.close()
