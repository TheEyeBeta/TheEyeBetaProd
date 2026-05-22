# Rule 04 — Infrastructure

## Docker Compose (dev)

- Every service **must** have a `healthcheck`. No exceptions.
- Services that depend on Postgres must use `depends_on: postgres: condition: service_healthy`.
- Use named volumes for persistent data. Never bind-mount DB data directories in CI.
- Compose file lives at repo root: `docker-compose.yml`.
- Supporting configs (prometheus.yml, otelcol.yaml, etc.) live in `infra/compose/`.

## Service Standards

| Service       | Image                                      | Purpose                        |
|---------------|--------------------------------------------|--------------------------------|
| postgres      | timescale/timescaledb-ha:pg17-latest       | Primary DB + time-series + vectors |
| redis         | redis:7-alpine                             | Cache + pub/sub                |
| nats          | nats:2-alpine                              | Messaging + JetStream          |
| minio         | minio/minio:RELEASE.2024-01-01T00-00-00Z   | Object storage (S3-compatible) |
| prometheus    | prom/prometheus:v2.54.0                    | Metrics scraping               |
| loki          | grafana/loki:3.2.0                         | Log aggregation                |
| tempo         | grafana/tempo:2.6.0                        | Distributed tracing            |
| grafana       | grafana/grafana:11.3.0                     | Dashboards                     |
| otel-collector| otel/opentelemetry-collector-contrib:0.113.0 | Telemetry pipeline            |

## Makefile Targets

All targets must be idempotent and safe to call multiple times.

- `up`: `docker compose up -d --wait` — wait for all healthchecks to pass.
- `down`: `docker compose down` — stop and remove containers (keep volumes).
- `nuke`: `docker compose down -v --remove-orphans` — **destroys all data**. Prompts for confirmation.
- `lint`: runs ruff, clang-format (check), sqlfluff, gitleaks.
- `format`: runs ruff format, clang-format (write), sqlfluff fix.
- `test`: `pytest -m "not smoke"` (no infra required).
- `test-smoke`: `pytest -m smoke` (requires `make up`).
- `db-migrate`: `alembic upgrade head` for all services.
- `build-cpp`: CMake configure + build for all C++ targets.

## Observability Wiring

- All Python services must instrument with `opentelemetry-sdk` and export to `otel-collector:4317`.
- Use `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` in dev.
- Traces → Tempo, Metrics → Prometheus (via otel-collector), Logs → Loki.
- Grafana datasources provisioned automatically from `infra/compose/grafana/provisioning/`.
