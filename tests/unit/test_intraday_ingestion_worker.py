"""Unit tests for intraday ingestion window and bucket math."""

from __future__ import annotations

from datetime import UTC, datetime

from workers.intraday_ingestion_worker import floor_bucket, is_market_session
from workers.intraday_providers import parse_bucket_bar, validate_intraday_bar


def test_market_window_boundaries() -> None:
    assert not is_market_session(datetime(2026, 6, 12, 13, 29, tzinfo=UTC))
    assert is_market_session(datetime(2026, 6, 12, 13, 31, tzinfo=UTC))
    assert is_market_session(datetime(2026, 6, 12, 20, 0, tzinfo=UTC))
    assert not is_market_session(datetime(2026, 6, 12, 20, 1, tzinfo=UTC))
    assert not is_market_session(datetime(2026, 6, 13, 14, 0, tzinfo=UTC))


def test_delay_bucket_math() -> None:
    now = datetime(2026, 6, 12, 15, 7, 30, tzinfo=UTC)
    bucket = floor_bucket(now, delay_minutes=15)
    assert bucket == datetime(2026, 6, 12, 14, 45, tzinfo=UTC)


def test_idempotent_bucket_floor() -> None:
    now = datetime(2026, 6, 12, 16, 0, 0, tzinfo=UTC)
    assert floor_bucket(now) == floor_bucket(now)


def test_parse_bucket_bar_matches_timestamp() -> None:
    payload = {
        "results": [
            {"t": 1_000, "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 10},
            {"t": 2_000, "o": 2, "h": 3, "l": 2, "c": 2.5, "v": 20},
        ],
    }
    assert parse_bucket_bar(payload, bucket_ms=2_000) == payload["results"][1]


def test_validate_intraday_bar_rejects_bad_ohlc() -> None:
    assert not validate_intraday_bar({"o": 0, "h": 1, "l": 1, "c": 1, "v": 1})
