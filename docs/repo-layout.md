# Repository Layout

This document is the canonical reference for the Zinc monorepo directory tree.
All agents and contributors must follow this structure. Update here first, then create files.

## Top-Level Tree

```
zinc/
├── .claude/                  # Claude Code agent rules
│   └── rules/
│       ├── 01-code-style.md
│       ├── 02-testing.md
│       ├── 03-security.md
│       └── 04-infrastructure.md
├── .cursor/                  # Cursor IDE rules
│   └── rules/
│       ├── bootstrap.mdc
│       └── project.mdc
├── .github/
│   └── workflows/
│       └── ci.yml
├── .sops.yaml                # SOPS encryption config (age key IDs)
├── .pre-commit-config.yaml
├── .clang-format
├── .gitignore
├── CLAUDE.md                 # Master agent guide
├── Makefile
├── README.md
├── docker-compose.yml        # All dev infra (10+ services)
├── pyproject.toml            # Workspace Python config (uv)
│
├── docs/
│   ├── adr/                  # Architecture Decision Records
│   │   ├── 0001-monorepo-structure.md
│   │   ├── 0002-database-choice.md
│   │   ├── 0003-messaging.md
│   │   ├── 0004-observability.md
│   │   ├── 0005-secrets-management.md
│   │   ├── 0006-ci-cd-strategy.md
│   │   └── 0007-container-strategy.md
│   ├── ci.md                 # CI matrix documentation
│   ├── repo-layout.md        # THIS FILE
│   └── templates/
│       ├── Dockerfile.template
│       ├── README.md         # README template for services
│       └── adr.md            # ADR template
│
├── infra/
│   ├── compose/              # Config files mounted into compose services
│   │   ├── prometheus.yml
│   │   ├── tempo.yaml
│   │   ├── otelcol.yaml
│   │   └── grafana/
│   │       └── provisioning/
│   │           ├── datasources/
│   │           │   └── datasources.yaml
│   │           └── dashboards/
│   │               └── dashboards.yaml
│   └── k8s/                  # Kubernetes manifests (future)
│
├── libs/                     # Shared Python libraries
│   └── zinc_core/            # (future) Core utilities
│
├── scripts/
│   ├── db-migrate.sh         # Wrapper to run Alembic migrations
│   └── check-secrets.sh      # Runs gitleaks on staged files
│
├── services/                 # Application services
│   ├── api/                  # HTTP API service (future)
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/
│   │   └── migrations/
│   └── worker/               # Background worker service (future)
│       ├── Dockerfile
│       ├── pyproject.toml
│       └── src/
│
└── tests/
    ├── unit/                 # Pure unit tests (no infra)
    ├── integration/          # Single-service integration tests
    └── smoke/                # Full-stack tests (requires make up)
        ├── conftest.py
        └── test_postgres.py
```

## Service Table (docker-compose.yml)

| Service        | Image                                         | Ports         | Purpose                        |
|----------------|-----------------------------------------------|---------------|--------------------------------|
| postgres       | timescale/timescaledb-ha:pg17-latest          | 5432          | DB + TimescaleDB + pgvector    |
| redis          | redis:7-alpine                                | 6379          | Cache + pub/sub                |
| nats           | nats:2-alpine                                 | 4222, 8222    | Messaging + JetStream          |
| minio          | minio/minio:latest                            | 9000, 9001    | Object storage                 |
| prometheus     | prom/prometheus:v2.54.1                       | 9090          | Metrics                        |
| loki           | grafana/loki:3.2.0                            | 3100          | Logs                           |
| tempo          | grafana/tempo:2.6.1                           | 3200          | Traces                         |
| grafana        | grafana/grafana:11.3.1                        | 3000          | Dashboards                     |
| otel-collector | otel/opentelemetry-collector-contrib:0.113.0  | 4317, 4318    | Telemetry pipeline             |

## Naming Conventions

- Services: `kebab-case`
- Python packages: `snake_case`
- Python modules: `snake_case`
- C++ files: `snake_case.cpp` / `snake_case.h`
- Docker images (custom): `zinc/<service>:<semver>`
- Migration files: `NNNN_short_description.py`
