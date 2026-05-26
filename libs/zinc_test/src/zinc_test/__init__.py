"""zinc_test — shared pytest fixtures for theeyebeta integration tests.

Import fixtures directly or let the pytest11 entry point auto-register them.
Services that need explicit registration can add to their conftest.py:

    pytest_plugins = ["zinc_test.plugin"]
"""

from __future__ import annotations

from zinc_test._infra import IntegrationInfra

__all__ = ["IntegrationInfra"]
