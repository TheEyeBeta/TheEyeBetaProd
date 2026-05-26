"""Unit tests for tb snapshots helpers."""

from __future__ import annotations

from datetime import date

import pytest
from tb.commands.snapshots import _business_days


@pytest.mark.unit
def test_business_days_typical_month_count() -> None:
    """January 2025 has 23 weekdays — close to the ~22 trading-day acceptance target."""
    days = _business_days(date(2025, 1, 1), date(2025, 1, 31))
    assert len(days) == 23
