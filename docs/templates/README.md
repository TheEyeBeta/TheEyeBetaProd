# <Service Name>

> One-line description of what this service does.

## Overview

Describe the service's responsibility in 2-3 sentences.
What domain does it own? What does it consume and produce?

## Architecture

- **Language:** Python 3.12
- **Framework:** (FastAPI / plain asyncio / etc.)
- **Database:** PostgreSQL (via psycopg3)
- **Messaging:** NATS JetStream
- **Observability:** OpenTelemetry → otel-collector

## Running Locally

```bash
# Start all infra (from repo root)
make up

# Run this service
cd services/<name>
uv run python -m src.<name>.main
```

## Configuration

All configuration is read from environment variables.

| Variable             | Default                                        | Description           |
|----------------------|------------------------------------------------|-----------------------|
| `DATABASE_URL`       | `postgresql://zinc:zinc_dev@localhost:5432/zinc` | Postgres connection   |
| `REDIS_URL`          | `redis://localhost:6379/0`                     | Redis connection      |
| `NATS_URL`           | `nats://localhost:4222`                        | NATS connection       |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317`            | OTEL collector        |

## API

_Describe endpoints or NATS subjects here._

## Tests

```bash
# Unit tests (no infra)
pytest -m unit tests/

# Smoke tests (requires make up)
pytest -m smoke tests/
```

## Migrations

```bash
# From repo root
make db-migrate

# Or directly
cd services/<name>
uv run alembic upgrade head
```
