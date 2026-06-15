"""Unit tests for the canonical indicator validation worker."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from workers.theeyebeta_indicator_worker import TheeyebetaIndicatorWorker


def _worker() -> TheeyebetaIndicatorWorker:
    return TheeyebetaIndicatorWorker(database_url="postgresql://unused/unused")


async def test_execute_raises_when_indicator_rows_missing() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[date(2026, 6, 12), 499, 480, 0])

    with pytest.raises(RuntimeError, match="ind_technical_daily"):
        await _worker().execute(conn, date(2026, 6, 12), dry_run=False)


async def test_dry_run_reports_coverage() -> None:
    conn = AsyncMock()
    conn.fetchval = AsyncMock(side_effect=[date(2026, 6, 12), 499, 480, 450])

    result = await _worker().execute(conn, date(2026, 6, 12), dry_run=True)

    assert result.records_written == 0
    assert result.metadata["indicator_rows"] == 450
    assert result.metadata["coverage"] == round(450 / 480, 4)
