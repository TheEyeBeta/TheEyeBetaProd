"""Migration rollback smoke test."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "db" / "alembic.ini"


@pytest.mark.integration
def test_migrations_downgrade_upgrade(postgres_container) -> None:  # noqa: ANN001
    """``alembic downgrade -1`` then ``upgrade head`` completes without error."""
    admin_url = postgres_container.get_connection_url()
    env = {**os.environ, "DATABASE_URL": admin_url}
    down = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "downgrade", "-1"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert down.returncode == 0, down.stderr
    up = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert up.returncode == 0, up.stderr
