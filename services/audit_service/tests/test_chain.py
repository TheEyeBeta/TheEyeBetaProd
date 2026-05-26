"""Unit tests for hash chain primitives."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from audit_service.chain import (  # noqa: E402
    GENESIS_HASH,
    AuditRow,
    canonical_row_json,
    compute_row_hash,
    verify_rows,
)

GENESIS_SEED = b"theeyebeta-genesis-2026-05-21"


@pytest.mark.unit
def test_genesis_hash_matches_seed() -> None:
    assert hashlib.sha256(GENESIS_SEED).digest() == GENESIS_HASH


@pytest.mark.unit
def test_compute_row_hash_is_deterministic() -> None:
    payload = canonical_row_json(
        ts=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        actor="svc",
        action="created",
        entity_type="order",
        entity_id="1",
        payload={"k": "v"},
    )
    h1 = compute_row_hash(GENESIS_HASH, payload)
    h2 = compute_row_hash(GENESIS_HASH, payload)
    assert h1 == h2
    assert len(h1) == 32


@pytest.mark.unit
def test_verify_rows_ok_for_linked_chain() -> None:
    ts = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    canonical = canonical_row_json(
        ts=ts,
        actor="oms",
        action="approved",
        entity_type="order",
        entity_id="abc",
        payload={"status": "approved"},
    )
    row_hash = compute_row_hash(GENESIS_HASH, canonical)
    rows = [
        AuditRow(
            id=1,
            ts=ts,
            actor="oms",
            action="approved",
            entity_type="order",
            entity_id="abc",
            payload={"status": "approved"},
            prev_hash=GENESIS_HASH,
            row_hash=row_hash,
        ),
    ]
    result = verify_rows(rows, initial_prev_hash=GENESIS_HASH)
    assert result.status == "OK"
    assert result.rows_checked == 1


@pytest.mark.unit
def test_verify_rows_detects_tampered_row_hash() -> None:
    ts = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    rows = [
        AuditRow(
            id=1,
            ts=ts,
            actor="oms",
            action="approved",
            entity_type="order",
            entity_id="abc",
            payload={"status": "approved"},
            prev_hash=GENESIS_HASH,
            row_hash=b"\x00" * 32,
        ),
    ]
    result = verify_rows(rows, initial_prev_hash=GENESIS_HASH)
    assert result.status == "MISMATCH"
    assert result.first_bad_row_id == 1
