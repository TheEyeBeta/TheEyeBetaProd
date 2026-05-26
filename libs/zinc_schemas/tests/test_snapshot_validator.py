"""Tests for packaged snapshot JSON Schema validation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from zinc_schemas.snapshot_validator import SnapshotValidationError, validate_snapshot

_VALID: dict = {
    "schema_version": 1,
    "market": "US",
    "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
    "as_of": "2025-01-15T23:59:59+00:00",
    "universe": [
        {
            "symbol": "AAPL",
            "instrument_id": 1,
            "sector": "Technology",
            "industry": None,
        }
    ],
    "prices": {
        "AAPL": {
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 105.0,
            "adj_close": 105.0,
            "volume": 1_000_000,
        }
    },
    "technicals": {
        "AAPL": {
            "atr14": 1.5,
            "adx14": 22.0,
            "rsi14": 55.0,
            "zscore20": 0.1,
            "bb_upper20_2": 110.0,
            "bb_lower20_2": 90.0,
        }
    },
    "macro": {"us.dgs10": 4.25},
    "news_summary": [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "headline": "Test",
            "tickers": ["AAPL"],
            "published_at": datetime(2025, 1, 15, 12, 0, tzinfo=UTC).isoformat(),
        }
    ],
}


@pytest.mark.unit
def test_validate_snapshot_accepts_valid_payload() -> None:
    """A well-formed v1 snapshot passes validation."""
    assert validate_snapshot(_VALID) is _VALID


@pytest.mark.unit
def test_validate_snapshot_rejects_unknown_root_field() -> None:
    """additionalProperties:false at root catches tampering."""
    tampered = {**_VALID, "injected": True}
    with pytest.raises(SnapshotValidationError) as exc_info:
        validate_snapshot(tampered)
    assert "injected" in str(exc_info.value) or "$" in str(exc_info.value)


@pytest.mark.unit
def test_validate_snapshot_rejects_invalid_market() -> None:
    """Market must be one of the v1 enum values."""
    bad = {**_VALID, "market": "XNAS"}
    with pytest.raises(SnapshotValidationError) as exc_info:
        validate_snapshot(bad)
    err = exc_info.value
    assert "market" in str(err).lower() or err.path == ("market",)


@pytest.mark.unit
def test_validate_snapshot_rejects_extra_price_field() -> None:
    """Price blocks forbid unknown properties."""
    tampered = {
        **_VALID,
        "prices": {
            "AAPL": {
                **_VALID["prices"]["AAPL"],
                "tampered": 1.0,
            }
        },
    }
    with pytest.raises(SnapshotValidationError) as exc_info:
        validate_snapshot(tampered)
    path = exc_info.value.path
    assert "prices" in path or "tampered" in str(exc_info.value)
