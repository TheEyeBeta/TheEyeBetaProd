---
paths: ["services/**", "libs/**", "tb/**"]
---

# Python Rules

## Version & Runtime

- **Python 3.12** — use `match`/`case`, `tomllib`, `ExceptionGroup` where appropriate.
- All services run under an async event loop; **no synchronous blocking calls** (DB, HTTP,
  filesystem) inside `async def` route handlers or task coroutines.
  Use `asyncio.to_thread()` only as a last resort, with a `# blocking:` comment.

## Framework

- **FastAPI** for all HTTP services.
- Route handlers must be `async def`. No `def` route handlers.
- Dependency injection via FastAPI `Depends()`; never import service-layer objects at module level.
- All request/response bodies are **Pydantic v2 models** — no plain `dict` crossing a service boundary.
- Mount a `/health` endpoint on every service that returns `{"status": "ok"}`.

## Linting & Formatting

- **ruff** handles both linting and import sorting:
  ```
  ruff check --fix .
  ruff format .
  ```
  Line length: 100. Config in `pyproject.toml` `[tool.ruff]`.
- **black** is configured as ruff's formatter backend — do not run `black` separately.
- **mypy `--strict`** on all code under `libs/`. Services target `--strict` minus
  `--disallow-untyped-decorators` (FastAPI decorator inference limitation).
- Fix all mypy errors; never use `# type: ignore` without a trailing comment explaining why.

## Configuration

- All environment variables declared in a `Settings` class extending
  `pydantic_settings.BaseSettings`.
- Settings loaded once at startup; injected via `Depends(get_settings)`.
- **Fail fast:** missing or invalid env vars raise `ValidationError` at import time in prod.
- Never read `os.environ` directly outside of the `Settings` class.

## Data & Persistence

- Database access via **psycopg 3** (async) or **SQLAlchemy 2 async** — never psycopg2.
- No raw SQL strings in service code; use parameterised queries or the ORM.
- **No synchronous DB calls inside async routes** — this is a hard error in CI (`asyncio-mode = auto`).
- Redis via `redis.asyncio`; NATS via `nats-py` async client.

## Project Structure (per service)

```
services/<svc>/
├── src/<svc>/
│   ├── __init__.py
│   ├── main.py        # FastAPI app factory
│   ├── routes/
│   ├── models/        # Pydantic DTOs
│   ├── db/            # SQLAlchemy models + session
│   └── settings.py    # BaseSettings
├── tests/
│   ├── conftest.py
│   ├── test_routes_*.py
│   └── test_*.py
├── migrations/        # Alembic
├── pyproject.toml
└── Dockerfile
```

## Testing

- **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"` in `pyproject.toml`).
- Tests live in `services/<svc>/tests/`; shared fixtures in `tests/conftest.py` at repo root.
- See `.claude/rules/tests.md` for naming and mocking conventions.
