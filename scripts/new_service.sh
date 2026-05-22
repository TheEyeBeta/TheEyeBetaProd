#!/usr/bin/env bash
# new_service.sh — scaffold a new theeyebeta application service
#
# Usage: bash scripts/new_service.sh <service-name>
# Example: bash scripts/new_service.sh portfolio-service
#
# Creates:
#   services/<name>/
#   ├── src/<name_snake>/
#   │   ├── __init__.py
#   │   ├── main.py        (FastAPI app factory)
#   │   ├── routes/
#   │   │   └── __init__.py
#   │   ├── models/
#   │   │   └── __init__.py
#   │   ├── db/
#   │   │   └── __init__.py
#   │   └── settings.py    (BaseSettings)
#   ├── tests/
#   │   └── conftest.py
#   ├── Dockerfile
#   └── pyproject.toml
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Validate argument ──────────────────────────────────────────────────────────
if [[ $# -lt 1 || -z "$1" ]]; then
  echo "Usage: bash scripts/new_service.sh <service-name>" >&2
  echo "  e.g. bash scripts/new_service.sh portfolio-service" >&2
  exit 1
fi

SVC_NAME="$1"
# Convert kebab-case to snake_case for Python package name
SVC_SNAKE="${SVC_NAME//-/_}"
SVC_DIR="${REPO_ROOT}/services/${SVC_NAME}"

if [[ -d "$SVC_DIR" ]]; then
  echo "✖ Directory already exists: ${SVC_DIR}" >&2
  exit 1
fi

echo "▶ Scaffolding service: ${SVC_NAME}"

# ── Directory tree ─────────────────────────────────────────────────────────────
mkdir -p \
  "${SVC_DIR}/src/${SVC_SNAKE}/routes" \
  "${SVC_DIR}/src/${SVC_SNAKE}/models" \
  "${SVC_DIR}/src/${SVC_SNAKE}/db" \
  "${SVC_DIR}/tests"

# ── pyproject.toml ─────────────────────────────────────────────────────────────
cat > "${SVC_DIR}/pyproject.toml" << TOML
[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"

[project]
name            = "${SVC_NAME}"
version         = "0.1.0"
description     = "theeyebeta ${SVC_NAME} service"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.4",
    "structlog>=24.4",
    "opentelemetry-instrumentation-fastapi>=0.48b0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/${SVC_SNAKE}"]
TOML

# ── settings.py ────────────────────────────────────────────────────────────────
cat > "${SVC_DIR}/src/${SVC_SNAKE}/settings.py" << PY
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    service_name: str = "${SVC_NAME}"
    debug: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"


@lru_cache
def get_settings() -> Settings:
    return Settings()
PY

# ── main.py ────────────────────────────────────────────────────────────────────
cat > "${SVC_DIR}/src/${SVC_SNAKE}/main.py" << PY
from __future__ import annotations

import structlog
from fastapi import FastAPI

from .settings import get_settings

log = structlog.get_logger()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="${SVC_NAME}",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    return app


app = create_app()
PY

# ── __init__.py files ──────────────────────────────────────────────────────────
for pkg in "" "/routes" "/models" "/db"; do
  touch "${SVC_DIR}/src/${SVC_SNAKE}${pkg}/__init__.py"
done

# ── tests/conftest.py ──────────────────────────────────────────────────────────
cat > "${SVC_DIR}/tests/conftest.py" << PY
"""${SVC_NAME} test fixtures."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ${SVC_SNAKE}.main import create_app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    ) as c:
        yield c
PY

# ── Dockerfile ─────────────────────────────────────────────────────────────────
cat > "${SVC_DIR}/Dockerfile" << 'DOCKER'
# ── Builder ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /build
COPY pyproject.toml ./
COPY src/ src/
RUN uv sync --no-dev --frozen

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="SERVICE_NAME_PLACEHOLDER"

RUN groupadd --gid 1001 nonroot \
 && useradd  --uid 1001 --gid nonroot --no-create-home nonroot

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src   /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER nonroot
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "src.SNAKE_NAME_PLACEHOLDER.main:app", "--host", "0.0.0.0", "--port", "8000"]
DOCKER

# Fix Dockerfile placeholders
sed -i "s/SERVICE_NAME_PLACEHOLDER/${SVC_NAME}/g" "${SVC_DIR}/Dockerfile"
sed -i "s/SNAKE_NAME_PLACEHOLDER/${SVC_SNAKE}/g" "${SVC_DIR}/Dockerfile"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "✔ Scaffolded: services/${SVC_NAME}/"
echo ""
echo "Manual steps remaining:"
echo "  1. Pick a port → add to docs/architecture.md §2.2"
echo "  2. Add 'ghcr.io/<org>/theeyebeta-${SVC_NAME}' to .github/workflows/release.yml matrix"
echo "  3. Add service to docker-compose.yml with healthcheck"
echo "  4. Write services/${SVC_NAME}/README.md (template: docs/templates/README.md)"
echo "  5. Add routes to docs/architecture.md §3.1"
echo "  6. Run: uv sync"
