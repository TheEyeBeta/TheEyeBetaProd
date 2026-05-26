# admin-service — FastAPI + JWT (port 7200)
# Build context: repository root (see docker-compose.yml).

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY services/admin_service/pyproject.toml services/admin_service/
COPY libs/zinc_schemas libs/zinc_schemas
COPY services/admin_service/main.py services/admin_service/
COPY services/admin_service/auth.py services/admin_service/
COPY services/admin_service/deps.py services/admin_service/
COPY services/admin_service/settings.py services/admin_service/
COPY services/admin_service/audit_log.py services/admin_service/
COPY services/admin_service/api services/admin_service/api/

RUN uv sync --package admin-service --no-dev --frozen

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="theeyebeta-admin-service"

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/services/admin_service/main.py /app/main.py
COPY --from=builder /build/services/admin_service/auth.py /app/auth.py
COPY --from=builder /build/services/admin_service/deps.py /app/deps.py
COPY --from=builder /build/services/admin_service/settings.py /app/settings.py
COPY --from=builder /build/services/admin_service/audit_log.py /app/audit_log.py
COPY --from=builder /build/services/admin_service/api /app/api

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ADMIN_SERVICE_HOST=0.0.0.0 \
    ADMIN_SERVICE_PORT=7200

# Docker socket access for tb status / service restarts (P-AD-04+).
USER root

EXPOSE 7200

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7200/admin/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7200"]
