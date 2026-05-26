# data-ingestion — FastAPI + APScheduler (port 7010)
# Build context: repository root (see docker-compose.yml).

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY libs/zinc_schemas libs/zinc_schemas
COPY services/data_ingestion/pyproject.toml services/data_ingestion/
COPY services/data_ingestion/main.py services/data_ingestion/
COPY services/data_ingestion/src services/data_ingestion/src/

RUN uv sync --package data-ingestion --no-dev --frozen

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="theeyebeta-data-ingestion"

RUN groupadd --gid 1001 nonroot \
 && useradd --uid 1001 --gid nonroot --no-create-home nonroot

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/services/data_ingestion/main.py /app/main.py
COPY --from=builder /build/services/data_ingestion/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_INGESTION_HOST=0.0.0.0 \
    DATA_INGESTION_PORT=7010

USER nonroot

EXPOSE 7010

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7010/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7010"]
