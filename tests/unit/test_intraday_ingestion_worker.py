"""Unit tests for intraday ingestion window and bucket math."""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc

from workers.intraday_ingestion_worker import floor_bucket, is_market_session


def test_market_window_boundaries() -> None:
    assert not is_market_session(datetime(2026, 6, 12, 13, 29, tzinfo=UTC))
    assert is_market_session(datetime(2026, 6, 12, 13, 31, tzinfo=UTC))
    assert is_market_session(datetime(2026, 6, 12, 20, 45, tzinfo=UTC))
    assert not is_market_session(datetime(2026, 6, 12, 20, 46, tzinfo=UTC))
    assert not is_market_session(datetime(2026, 6, 13, 14, 0, tzinfo=UTC))


def test_delay_bucket_math() -> None:
    now = datetime(2026, 6, 12, 15, 7, 30, tzinfo=UTC)
    bucket = floor_bucket(now, delay_minutes=15)
    assert bucket == datetime(2026, 6, 12, 14, 45, tzinfo=UTC)


def test_idempotent_bucket_floor() -> None:
    now = datetime(2026, 6, 12, 16, 0, 0, tzinfo=UTC)
    assert floor_bucket(now) == floor_bucket(now)
