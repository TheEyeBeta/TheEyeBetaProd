"""Admin-service settings tests."""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from settings import Settings  # noqa: E402


def test_dataapi_default_uses_prod_debug_hostname() -> None:
    """TheEyeBetaProd defaults DataAPI bridge calls through the prod tunnel."""
    settings = Settings()

    assert settings.dataapi_url == "https://dataapiprod.theeyebeta.store"

