"""pytest plugin entry-point registered via the ``pytest11`` entry-point group.

When ``zinc-test`` is installed (via ``uv sync`` in the workspace), pytest
loads this module automatically and every fixture defined here becomes
available to all test sessions without any explicit ``pytest_plugins``
declaration.

Services that prefer explicit opt-in can add to their ``conftest.py``::

    pytest_plugins = ["zinc_test.plugin"]
"""

from __future__ import annotations

# Re-export all fixtures so they are visible to pytest's fixture collection
# mechanism when this module is loaded as a plugin.
from zinc_test.fixtures.containers import (
    minio_container,
    nats_container,
    postgres_container,
    redis_container,
)
from zinc_test.fixtures.database import (
    alembic_upgraded,
    integration_infra,
    seed_data,
)
from zinc_test.fixtures.mocks import (
    alpaca_mock,
    llm_gateway_mock,
)

__all__ = [
    # containers
    "postgres_container",
    "redis_container",
    "nats_container",
    "minio_container",
    # database
    "alembic_upgraded",
    "seed_data",
    "integration_infra",
    # mocks
    "llm_gateway_mock",
    "alpaca_mock",
]
