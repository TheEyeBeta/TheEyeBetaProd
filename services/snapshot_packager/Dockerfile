# snapshot-packager — FastAPI + NATS consumer (port 7011)
# Requires zinc_native extensions: run `make build-cpp` before `docker build`.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY libs/zinc_schemas libs/zinc_schemas
COPY libs/zinc_native libs/zinc_native
COPY services/snapshot_packager/pyproject.toml services/snapshot_packager/
COPY services/snapshot_packager/main.py services/snapshot_packager/
COPY services/snapshot_packager/src services/snapshot_packager/src/

RUN uv sync --package snapshot-packager --no-dev --frozen

FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="theeyebeta-snapshot-packager"

RUN groupadd --gid 1001 nonroot \
 && useradd --uid 1001 --gid nonroot --no-create-home nonroot

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/services/snapshot_packager/main.py /app/main.py
COPY --from=builder /build/services/snapshot_packager/src /app/src
COPY --from=builder /build/libs/zinc_native/zinc_native /app/zinc_native_ext

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src:/app/zinc_native_ext" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SNAPSHOT_PACKAGER_HOST=0.0.0.0 \
    SNAPSHOT_PACKAGER_PORT=7011

USER nonroot

EXPOSE 7011

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7011/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7011"]
