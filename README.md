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
| [SERVICES_STATUS.md](SERVICES_STATUS.md) | Live snapshot of which services are actually deployed vs. code-complete-but-undeployed |
| [docs/data-model.md](docs/data-model.md) | The real `theeyebeta` schema, hypertables/pgvector, and the public/iam shared-instance gotcha |
| [docs/db-state-map.md](docs/db-state-map.md) | Generated diagnostic of every schema/table/role on the shared Postgres instance |
| [docs/agents.md](docs/agents.md) | LLM agent hierarchy (`config/agents/hierarchy.yaml`), LiteLLM/OpenAI routing, guard-service rules |
| [docs/admin-service.md](docs/admin-service.md) | Admin UI reference — Jinja2/htmx pages, order management, proposal workflow |
| [docs/headless-operations.md](docs/headless-operations.md) | `tb` CLI reference, day-to-day ops, deployment runbook, incident response |
| [docs/secrets.md](docs/secrets.md) | sops + age key management, 1Password workflow, CI setup |
| [docs/adr/](docs/adr/) | Architecture Decision Records (0001–0011) |

---

## Service Map

> Full table with deployment status and SLOs: [docs/architecture.md §2.2](docs/architecture.md#22-port-map),
> live deployed-vs-scaffolded snapshot: [SERVICES_STATUS.md](SERVICES_STATUS.md).
> **Only the rows marked "deployed" below are actually running** — everything else is real,
> tested code with no systemd unit / compose entry yet.

### Application services

| Service | Port | Status | Purpose |
|---------|------|--------|---------|
| `data-ingestion` | 7010 | deployed (docker-compose) | Market data ingestion from feeds; publishes to NATS |
| `snapshot-packager` | 7011 | deployed (systemd, `theeye-snapshot-packager.service`) | Packages OHLCV + orderbook snapshots to MinIO |
| `llm-gateway` | 4000 | deployed (docker-compose) | LiteLLM proxy to OpenAI (gpt-5 / gpt-4o-mini); rate-limiting and logging |
| `admin-service` | 7200 | deployed (docker-compose, Tailscale ACL) | Jinja2 + htmx admin dashboard (JWT + MFA) |
| `agent_runtime` | 8004 | deployed (systemd) | Executes research and trading agents; consumes NATS |
| `master_orchestrator` | 7050 | deployed (systemd, `theeye-master-orchestrator.service`) | Coordinates the two-loop cycle; routes proposals to execution or research |
| `guard_service` | 7040 (gRPC) / 8005 | code-complete, not deployed | Pre-trade signal validation, position limits, circuit breakers |
| `risk_service` | 7060 (gRPC) | unit staged, disabled | Real-time P&L, VaR, margin calculations — blocked on "0 portfolios", not the unit |
| `compliance_service` | 7070 (gRPC) / 8008 | deployed (systemd, `theeye-compliance-service.service`) | Regulatory rule checks; writes to audit_log |
| `oms` | 7080 | deployed (systemd, `theeye-oms.service`) | Order management — lifecycle, fills, cancellations. Paper-mode; live trading gated separately (see `broker_adapter_alpaca.live_gate`) |
| `broker_adapter_alpaca` | 7090 | deployed (systemd, `theeye-broker-adapter-alpaca.service`) | Alpaca Markets REST + WebSocket adapter. Running in paper mode; live mode requires DB + Redis approval (`live_gate.py`) |
| `backtest_engine` | 7100 | code-complete, not deployed | Vectorised backtester; reads snapshots from MinIO |
| `audit_service` | 7110 | code-complete, not deployed | Audit **verify**/export API — `audit_log` writes are already live via `BaseWorker`, independent of this service |
| `rnd_agent` | 7120 | code-complete, not deployed | Research agent — generates proposals from historical data + LLM |

The actual production data pipeline runs separately from the table above: ~20 timer-driven
`workers/*.py` jobs installed from `deploy/systemd/theeye-*.timer` (macro, intraday, daily
pipeline, sector, market-cap, gap-sentinel, backup, news, etc.). The externally-facing market-data
API is a **separate sibling repo**, `TheEyeBetaDataAPI` (`theeyebeta-dataapi.service`, :7000) — not
part of this repo.

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

> From [docs/architecture.md §3.3](docs/architecture.md#33-the-two-loop-cycle).
> **Most of this is now live.** `data-ingestion`, `llm-gateway`, `admin-service` (docker-compose),
> `agent_runtime`, `snapshot-packager`, `master_orchestrator`, `compliance_service`, `oms`, and
> `broker_adapter_alpaca` (systemd) are all running in paper mode. `guard_service`,
> `backtest_engine`, and `rnd_agent` still have no deploy unit. See the Service Map above.

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
        ADM[admin-service :7200]
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

The Makefile is self-documenting — run `make help` for the full, current list (20+ targets,
each with a one-line description). The most commonly used:

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
