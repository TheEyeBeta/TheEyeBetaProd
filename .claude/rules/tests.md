---
paths: ["**/tests/**", "**/*_test.cpp"]
---

# Test Rules

## Naming Conventions

### Python
- Function names follow either convention — pick one per test file and be consistent:
  - `test_<unit>_<scenario>_<expectation>` — e.g. `test_order_router_missing_symbol_returns_422`
  - `Given_<context>_When_<action>_Then_<result>` via a class:
    ```python
    class GivenAnAuthenticatedUser:
        async def when_symbol_is_missing_then_422(self, client): ...
    ```
- Test module names: `test_<module_under_test>.py`
- Fixture names: descriptive nouns — `authenticated_client`, `seeded_db`, `mock_alpaca`

### C++
- GoogleTest macro: `TEST(SuiteName, GivenX_WhenY_ThenZ)`
- Suite name matches the class or subsystem under test: `OrderBookTest`, `EigenHelpersTest`

## What to Mock — and What Not To

| Dependency | Mock? | Rationale |
|------------|-------|-----------|
| Internal Python modules (own code) | **Never** | Mocking internals hides integration bugs |
| Anthropic API | **Yes** — use `respx` or `unittest.mock` | External, paid, non-deterministic |
| OpenAI API | **Yes** — same as Anthropic | External, paid, non-deterministic |
| Alpaca Markets API | **Yes** — use `respx` fixture | External, stateful (orders) |
| Postgres | **No** — use testcontainers | Real DB behaviour required |
| Redis | **No** — use testcontainers | Real pub/sub behaviour required |
| NATS | **No** — use testcontainers | Real JetStream behaviour required |
| MinIO | **No** — use testcontainers | Real object storage required |
| Filesystem | **No** — use `tmp_path` fixture | Cheap and accurate |

## Testcontainers (Integration Tests)

- Use the `testcontainers` Python library for all infrastructure in integration tests.
- Shared fixtures live in `tests/conftest.py` (repo root) — do not duplicate per service.
- Container fixture scope: `session` for read-only infra; `function` if state is mutated.

```python
# tests/conftest.py
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("timescale/timescaledb-ha:pg17-latest") as pg:
        yield pg.get_connection_url()
```

- Always pass `reuse=False` in CI (don't rely on Docker layer caching for container identity).
- After the container starts, run `alembic upgrade head` before yielding to tests.

## Markers & CI Separation

```
@pytest.mark.unit        # no I/O; runs in <10 ms; always runs in CI
@pytest.mark.integration # testcontainers; runs in CI on every PR
@pytest.mark.smoke       # full stack; requires make up; runs on main push only
```

- `pytest -m "not smoke"` must complete without infra in CI unit/integration jobs.
- Tests without a marker are treated as `unit` (fail fast if they perform I/O).

## Coverage

- `libs/` target: **≥ 85 %** line coverage. CI fails below this threshold.
- `services/` target: **≥ 70 %** line coverage.
- Coverage report uploaded to Codecov on every PR.
- Do **not** use `# pragma: no cover` without a comment explaining why.

## Async Tests

- `asyncio_mode = "auto"` in `pyproject.toml` — all `async def test_*` functions run
  automatically without a `@pytest.mark.asyncio` decorator.
- Never use `asyncio.run()` inside a test function.
- Use `httpx.AsyncClient` (via `pytest-httpx` or `ASGITransport`) for FastAPI route tests.
