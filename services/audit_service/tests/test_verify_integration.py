"""Integration: out-of-band insert breaks verify at first affected row."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS = Path(__file__).resolve().parent
for _p in (_SRC, _TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from audit_service.chain import (  # noqa: E402
    append_chained_row,
    verify_range,
)

if TYPE_CHECKING:
    from services.audit_service.tests.conftest import PostgresInfra


def _normalize_dsn(dsn: str) -> str:
    return dsn.replace("+asyncpg", "").replace("+psycopg", "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_verify_detects_out_of_band_psql_insert(postgres_infra: PostgresInfra) -> None:
    """Acceptance: tampered row is reported at the first bad chain link."""
    dsn = _normalize_dsn(postgres_infra.database_url)
    base_ts = datetime.now(tz=UTC).replace(microsecond=0) - timedelta(minutes=5)

    await append_chained_row(
        dsn,
        actor="oms",
        action="proposed",
        entity_type="order",
        entity_id="order-1",
        payload={"step": 1},
        ts=base_ts,
    )
    await append_chained_row(
        dsn,
        actor="oms",
        action="approved",
        entity_type="order",
        entity_id="order-1",
        payload={"step": 2},
        ts=base_ts + timedelta(seconds=1),
    )

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            INSERT INTO theeyebeta.audit_log
                (ts, actor, action, entity_type, entity_id, payload, prev_hash, row_hash)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                base_ts + timedelta(seconds=2),
                "attacker",
                "tampered",
                "order",
                "order-1",
                json.dumps({"step": "evil"}),
                b"\x01" * 32,
                b"\x02" * 32,
            ),
        )
        await conn.commit()
        await cur.close()

    result = await verify_range(
        dsn,
        from_ts=base_ts - timedelta(minutes=1),
        to_ts=base_ts + timedelta(hours=1),
    )
    assert result.status == "MISMATCH"
    assert result.first_bad_row_id is not None
    assert result.first_bad_row_id >= 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_append_and_verify_ok(postgres_infra: PostgresInfra) -> None:
    dsn = _normalize_dsn(postgres_infra.database_url)
    ts = datetime.now(tz=UTC).replace(microsecond=0) + timedelta(minutes=5)
    await append_chained_row(
        dsn,
        actor="risk",
        action="validated",
        entity_type="order",
        entity_id="x",
        payload={"ok": True},
        ts=ts,
    )
    result = await verify_range(
        dsn,
        from_ts=ts - timedelta(minutes=1),
        to_ts=ts + timedelta(minutes=1),
    )
    assert result.status == "OK"
    assert result.rows_checked == 1
