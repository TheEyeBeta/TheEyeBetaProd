"""Unit tests for SupabaseSyncWorker."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workers.supabase_sync_worker import (
    SupabaseSyncWorker,
    prepare_snapshot_row,
    safe_float,
    upsert_stock_snapshots,
    write_shadow_report,
)


def test_prepare_snapshot_row_maps_core_fields() -> None:
    synced_at = datetime(2026, 6, 16, 14, 0, tzinfo=UTC)
    row = prepare_snapshot_row(
        {
            "ticker_id": 10,
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "last_price": "190.12",
            "last_price_ts": datetime(2026, 6, 16, 13, 55, tzinfo=UTC),
            "price_change_pct": 1.25,
            "rsi_14": 55.5,
            "macd_hist": 0.42,
            "latest_signal": "BUY",
            "signal_strategy": "ema_cross",
            "signal_confidence": 0.81,
            "signal_ts": datetime(2026, 6, 16, 13, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 6, 16, 13, 55, tzinfo=UTC),
        },
        synced_at=synced_at,
    )

    assert row["ticker_id"] == 10
    assert row["ticker"] == "AAPL"
    assert row["macd_histogram"] == pytest.approx(0.42)
    assert row["signal_timestamp"] == "2026-06-16T13:00:00+00:00"
    assert row["synced_at"] == synced_at.isoformat()


def test_safe_float_rejects_nan() -> None:
    assert safe_float(float("nan")) is None
    assert safe_float("1.5") == pytest.approx(1.5)


async def test_shadow_mode_writes_report_without_supabase_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setattr("workers.supabase_sync_worker.REPORT_DIR", tmp_path)

    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "ticker_id": 1,
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "last_price": 100.0,
            },
        ],
    )

    with patch("workers.supabase_sync_worker.upsert_stock_snapshots") as upsert:
        worker = SupabaseSyncWorker(shadow=True, database_url="postgresql://unused/unused")
        output = await worker.execute(conn, date(2026, 6, 16), dry_run=False)

    upsert.assert_not_called()
    assert output.records_written == 0
    assert output.metadata["shadow"] is True
    report = tmp_path / "supabase_shadow_2026-06-16.md"
    assert report.exists()


async def test_live_mode_upserts_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")

    conn = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "ticker_id": 1,
                "ticker": "AAPL",
                "company_name": "Apple Inc.",
                "last_price": 100.0,
            },
        ],
    )

    with patch(
        "workers.supabase_sync_worker.upsert_stock_snapshots",
        MagicMock(),
    ) as upsert:
        worker = SupabaseSyncWorker(shadow=False, database_url="postgresql://unused/unused")
        output = await worker.execute(conn, date(2026, 6, 16), dry_run=False)

    upsert.assert_called_once()
    assert output.records_written == 1
    assert output.metadata["shadow"] is False


def test_upsert_stock_snapshots_posts_batches() -> None:
    with patch("workers.supabase_sync_worker.httpx.Client") as client_cls:
        client = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        client.post.return_value = response
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client_cls.return_value = client

        upsert_stock_snapshots(
            supabase_url="https://example.supabase.co",
            service_key="secret",
            rows=[{"ticker_id": 1, "ticker": "AAPL"}],
        )

    client.post.assert_called_once()
    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["params"] == {"on_conflict": "ticker_id"}
    assert call_kwargs["json"] == [{"ticker_id": 1, "ticker": "AAPL"}]


def test_write_shadow_report_includes_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("workers.supabase_sync_worker.REPORT_DIR", tmp_path)
    path = write_shadow_report(
        trade_date=date(2026, 6, 16),
        canonical_count=10,
        prepared_count=10,
        sample={"ticker_id": 1, "ticker": "AAPL"},
    )
    assert path.parent == tmp_path
    text = path.read_text(encoding="utf-8")
    assert "shadow" in text
    assert "AAPL" in text
