# theeyebeta

> A self-hosted, real-time market-intelligence and algorithmic-research platform —
> runs entirely on a dedicated Mac mini, combining a Python/FastAPI backend,
> C++ compute modules, LLM-assisted agents, and a full observability stack.

---

## TL;DR Quickstart

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | ≥ 4.x | docker.com |
| [uv](https://docs.astral.sh/uv/) | ≥ 0.5 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [sops](https://github.com/mozilla/sops) | ≥ 3.9 | `brew install sops` |
| [age](https://age-encryption.org/) | ≥ 1.2 | `brew install age` |
| [1Password CLI](https://developer.1password.com/docs/cli/) | ≥ 2.x | `brew install 1password-cli` |

### First-time setup

```bash
# 1. Clone
git clone https://github.com/<org>/theeyebeta
cd theeyebeta

# 2. Install Python workspace deps
uv sync

# 3. Restore your age private key from 1Password
op read "op://Private/theeyebeta age key/password" \
  > ~/.config/sops/age/keys.txt && chmod 600 ~/.config/sops/age/keys.txt

# 4. Decrypt dev secrets → .env
make decrypt-env          # reads secrets/dev.enc.yaml

# 5. Start all infra
make up                   # docker compose up -d --wait (≈90 s)

# 6. Install git hooks
make install-hooks
```

### Open dashboards

| Dashboard | URL | Credentials |
|-----------|-----|-------------|
| Grafana | http://localhost:3000 | admin / see `.env` |
| MinIO console | http://localhost:9001 | see `.env` |
| NATS monitoring | http://localhost:8222 | — |
| Prometheus | http://localhost:9090 | — |
| Admin UI | http://localhost:8080 | see `.env` |

---

## What Lives Where

| Document | Contents |
|----------|----------|
| [docs/architecture.md](docs/architecture.md) | System overview, production host config (§2.2), service topology (§3.1–3.3), data model (§4), repo layout (§14), runbook (§15) |
| [docs/data-model.md](docs/data-model.md) | PostgreSQL schema, TimescaleDB hypertables, pgvector indexes, Alembic migration conventions |
| [docs/agents.md](docs/agents.md) | LLM agent architecture, prompt templates, guard-service rules, rnd-agent workflow |
| [docs/admin-service.md](docs/admin-service.md) | Admin UI reference — Jinja2/htmx pages, order management, proposal workflow |
| [docs/headless-operations.md](docs/headless-operations.md) | `tb` CLI reference, day-to-day ops, deployment runbook, incident response |
| [docs/secrets.md](docs/secrets.md) | sops + age key management, 1Password workflow, CI setup |
| [docs/adr/](docs/adr/) | Architecture Decision Records (0001–0007) |

---

## Service Map

> Full table with ports, dependencies, and SLOs: [docs/architecture.md §3.1](docs/architecture.md#31-service-inventory)

### Application services

| Service | Port | Visibility | Purpose |
|---------|------|-----------|---------|
| `data-ingestion` | 8001 | private | Market data ingestion from feeds; publishes to NATS |
| `snapshot-packager` | 8002 | private | Packages OHLCV + orderbook snapshots to MinIO |
| `llm-gateway` | 8003 | private | Unified LLM proxy (Anthropic / OpenAI) with rate-limiting and logging |
| `agent-runtime` | 8004 | private | Executes research and trading agents; consumes NATS |
| `guard-service` | 8005 | private | Pre-trade signal validation, position limits, circuit breakers |
| `master-orchestrator` | 8006 | private | Coordinates the two-loop cycle; routes proposals to execution or research |
| `risk-service` | 8007 | private | Real-time P&L, VaR, margin calculations |
| `compliance-service` | 8008 | private | Regulatory rule checks; writes to audit_log |
| `oms` | 8009 | private | Order management — lifecycle, fills, cancellations |
| `broker-adapter-alpaca` | 8010 | private | Alpaca Markets REST + WebSocket adapter |
| `backtest-engine` | 8011 | private | Vectorised backtester; reads snapshots from MinIO |
| `audit-service` | 8012 | private | Append-only audit trail; audit_log is write-once |
| `rnd-agent` | 8013 | private | Research agent — generates proposals from historical data + LLM |
| `admin-service` | 8080 | **public** (Tailscale) | Jinja2 + htmx admin dashboard |

### Infrastructure services

| Service | Port(s) | Notes |
|---------|---------|-------|
| PostgreSQL 17 + TimescaleDB + pgvector | 5432 | All services share one DB; isolated by schema |
| Redis 7 | 6379 | Cache + pub/sub |
| NATS 2 + JetStream | 4222, 8222 | Primary messaging backbone |
| MinIO | 9000 (API), 9001 (console) | 9001 exposed over Tailscale |
| Prometheus | 9090 | |
| Loki | 3100 | |
| Tempo | 3200 | |
| Grafana | 3000 | Exposed over Tailscale |
| OTel Collector | 4317, 4318 | OTLP receiver |

---

## The Two-Loop Architecture

> From [docs/architecture.md §3.3](docs/architecture.md#33-the-two-loop-cycle)

```mermaid
flowchart LR
    subgraph FAST ["⚡ Fast Loop — Execution  (ms → s)"]
        direction LR
        DI[data-ingestion]  -->|NATS market.tick| AR[agent-runtime]
        AR                  -->|signal| GS[guard-service]
        GS                  -->|approved signal| MO[master-orchestrator]
        MO                  -->|order intent| RS[risk-service]
        RS                  -->|risk-cleared| OMS[oms]
        OMS                 -->|order| BA[broker-adapter-alpaca]
        BA                  -->|fill / reject| OMS
        OMS                 -->|execution report| MO
    end

    subgraph SLOW ["🧠 Slow Loop — Research  (min → h)"]
        direction LR
        SP[snapshot-packager] -->|parquet → MinIO| BE[backtest-engine]
        BE                    -->|backtest result| RNA[rnd-agent]
        RNA                   -->|LLM prompt| LLM[llm-gateway]
        LLM                   -->|structured proposal| MO
    end

    subgraph OPS ["Operations"]
        ADM[admin-service :8080]
        CS[compliance-service]
        AS[audit-service]
    end

    MO  -->|proposal log|   CS
    MO  -->|dashboard feed| ADM
    OMS -->|trade event|    AS
    CS  -->|audit entry|    AS

    NATS{{NATS\nJetStream}} -.->|subjects| DI
    NATS                    -.->|subjects| AR
    PG[(PostgreSQL)]        -.->|state|    OMS
    PG                      -.->|state|    RS
```

---

## Day-to-Day Operations

The `tb` CLI is the primary operational interface on the production host.

```bash
tb status                  # health summary of all services
tb logs market-service     # tail a service (alias: make logs-market-service)
tb deploy market-service   # deploy a single service (requires confirmation)
tb backtest run <id>       # trigger a backtest job
```

Full reference → [docs/headless-operations.md](docs/headless-operations.md)  
Production runbook → [docs/architecture.md §15](docs/architecture.md#15-operations-runbook)

---

## Development Commands

```bash
make up              # start infra
make down            # stop infra
make lint            # ruff + mypy + clang-format + sqlfluff
make format          # auto-fix formatting
make test            # unit tests (no infra)
make test-int        # integration tests (testcontainers)
make test-smoke      # smoke tests (requires make up)
make build-cpp       # CMake + Conan
make db-migrate      # alembic upgrade head (local)
make db-revision MSG="add orders table"   # new migration
make decrypt-env     # decrypt secrets → .env
make nuke CONFIRM=yes  # ⚠ destroy all data
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

Quick rules:
- Branch from `main`: `git checkout -b feat/<name>`
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) — enforced by pre-commit hook
- All CI checks must be green before requesting review
- Architectural changes require an ADR in `docs/adr/`
- Secrets go through sops + age — never plaintext in commits

---

## License

MIT — see [LICENSE](LICENSE).
