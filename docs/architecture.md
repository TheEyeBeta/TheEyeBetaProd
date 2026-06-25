# Architecture

> **Status:** Living document — update when the system changes, not after.
> Sections are referenced by CLAUDE.md, .cursor/rules/, and .claude/rules/.

---

## Table of Contents

0. [The Eye Terminal (official direction)](#0-the-eye-terminal-official-direction)
1. [Overview](#1-overview)
2. [Production Host](#2-production-host)
   - [2.1 Hardware](#21-hardware)
   - [2.2 Port Map](#22-port-map)
3. [Service Topology](#3-service-topology)
   - [3.1 Service Inventory](#31-service-inventory)
   - [3.2 Communication Patterns](#32-communication-patterns)
   - [3.3 The Two-Loop Cycle](#33-the-two-loop-cycle)
4. [Data Model](#4-data-model)
   - [4.1 Core Schemas](#41-core-schemas)
   - [4.2 Migration Modules](#42-migration-modules)
5. [LLM & Agent Layer](#5-llm--agent-layer)
6. [Security](#6-security)
7. [Observability](#7-observability)
8. [C++ Compute Layer](#8-c-compute-layer)
9. [Admin Service](#9-admin-service)
10. [Secrets Management](#10-secrets-management)
11. [CI/CD Pipeline](#11-cicd-pipeline)
12. [Deployment](#12-deployment)
13. [Disaster Recovery](#13-disaster-recovery)
14. [Repository Layout](#14-repository-layout)
    - [14.1 Directory Tree](#141-directory-tree)
15. [Operations Runbook](#15-operations-runbook)

---

## 0. The Eye Terminal (official direction)

The **operator command terminal** — what operators use to see and safely control the stack — is defined in **[the-eye-terminal-architecture.md](the-eye-terminal-architecture.md)**.

That document is the authoritative direction for: Control Plane Law, Edge Route Law, MASTER_ADMIN, the Edge Route Registry, Cloudflare/Data API routing (`:7000`), the `dataapiprod` `:9500` incident, and frontend/backend parity. The living service inventory below remains the engine-room reference; Terminal coverage gaps are tracked in §23 of the direction doc.

**Implemented today:** `services/admin_service/` on port **7200** at `https://admin.theeyebeta.store/admin/*`.

---

## 1. Overview

theeyebeta is a self-hosted algorithmic-research and market-intelligence platform.
It runs a **two-loop architecture**: a fast execution loop (ms → s) driven by live
market data, and a slow research loop (min → h) driven by LLM agents and backtesting.

All services are Python 3.12 / FastAPI, sharing PostgreSQL 17 (+ TimescaleDB + pgvector),
Redis 7, and NATS 2 JetStream. Performance-critical paths use C++20 via nanobind bindings.

---

## 2. Production Host

### 2.1 Hardware

| Item | Value |
|------|-------|
| Machine | Mac mini (2023, M2 Pro) |
| OS | Linux (Asahi / Fedora) |
| RAM | 32 GB |
| Storage | 1 TB NVMe |
| Network | 1 Gbit Ethernet + Tailscale mesh |

### 2.2 Port Map

> All ports bind to `127.0.0.1` except where noted. Tailscale provides external access.

| Service | Port | Bind | Notes |
|---------|------|------|-------|
| `data-ingestion` | 8001 | 127.0.0.1 | |
| `snapshot-packager` | 8002 | 127.0.0.1 | |
| `llm-gateway` | 8003 | 127.0.0.1 | |
| `agent-runtime` | 8004 | 127.0.0.1 | |
| `guard-service` | 8005 | 127.0.0.1 | |
| `master-orchestrator` | 8006 | 127.0.0.1 | |
| `risk-service` | 8007 | 127.0.0.1 | |
| `compliance-service` | 8008 | 127.0.0.1 | |
| `oms` | 8009 | 127.0.0.1 | |
| `broker-adapter-alpaca` | 7090 | 127.0.0.1 | |
| `backtest-engine` | 7100 | 127.0.0.1 | |
| `audit-service` | 7110 | 127.0.0.1 | Hash-chained audit log + WORM checkpoints |
| `rnd-agent` | 7120 | 127.0.0.1 | Nightly R&D proposals (`tb_rnd_readonly`) |
| `admin-service` | 7200 | 0.0.0.0 | Tailscale + Cloudflare (`/admin/*`) |
| PostgreSQL | 5432 | 127.0.0.1 | |
| Redis | 6379 | 127.0.0.1 | |
| NATS client | 4222 | 127.0.0.1 | |
| NATS monitor | 8222 | 127.0.0.1 | |
| MinIO S3 API | 9000 | 127.0.0.1 | |
| MinIO console | 9001 | 0.0.0.0 | Tailscale-accessible |
| Grafana | 3000 | 127.0.0.1 | Tailscale-accessible via tunnel |
| Prometheus | 9090 | 127.0.0.1 | |
| Loki | 3100 | 127.0.0.1 | |
| Tempo | 3200 | 127.0.0.1 | |
| OTel Collector gRPC | 4317 | 127.0.0.1 | |
| OTel Collector HTTP | 4318 | 127.0.0.1 | |

---

## 3. Service Topology

### 3.1 Service Inventory

_See the [README service map](../README.md#service-map) for a condensed view._

### 3.2 Communication Patterns

| Pattern | Used for | Technology |
|---------|----------|-----------|
| Request/response | Synchronous service calls | HTTP (FastAPI → httpx) |
| Event stream | Market data, fills, signals | NATS JetStream subjects |
| Durable queue | Backtest jobs, research tasks | NATS JetStream consumers |
| Shared state | Order book, positions | PostgreSQL |
| Cache | Rate limits, session state | Redis |
| Object storage | Snapshots, parquet files, models | MinIO |

### 3.3 The Two-Loop Cycle

_Diagram is embedded in the [README](../README.md#the-two-loop-architecture)._

**Fast loop** (execution): `data-ingestion` → `agent-runtime` → `guard-service` →
`master-orchestrator` → `risk-service` → `oms` → `broker-adapter-alpaca` → fills back to `oms`.

**Slow loop** (research): `snapshot-packager` → `backtest-engine` → `rnd-agent` →
`llm-gateway` → proposals → `master-orchestrator`.

---

## 4. Data Model

_See [docs/data-model.md](data-model.md) for the full schema._

### 4.1 Core Schemas

| Schema | Owner service | Contents |
|--------|---------------|----------|
| `public` | shared | users, audit_log, instruments |
| `market` | data-ingestion | ticks (hypertable), ohlcv (hypertable) |
| `orders` | oms | orders, fills, positions |
| `risk` | risk-service | limits, var_snapshots |
| `research` | rnd-agent | proposals, backtest_runs |
| `compliance` | compliance-service | rule_checks, alerts |

### 4.2 Migration Modules

One Alembic migration per module (enforced by `.claude/rules/sql.md`):

| Module | Revision prefix | Contents |
|--------|-----------------|----------|
| bootstrap | 0001 | Extensions, roles |
| instruments | 0002 | instruments, trading_sessions |
| market | 0003 | ticks hypertable, ohlcv |
| orders | 0004 | orders, fills, positions |
| risk | 0005 | limits, var_snapshots |
| research | 0006 | proposals, backtest_runs |
| compliance | 0007 | rule_checks, audit_log |
| users | 0008 | users, sessions |

---

## 5. LLM & Agent Layer

_See [docs/agents.md](agents.md) for full detail._

---

## 6. Security

_See [docs/secrets.md](secrets.md) for secrets management._
All services run as non-root in containers. mTLS between services in production is
provided by Tailscale. Audit log rows are append-only — see §4.1.

---

## 7. Observability

Traces → Tempo, Metrics → Prometheus, Logs → Loki. All via OTel Collector.
Grafana datasources are auto-provisioned with trace ↔ log correlation.
See `infra/grafana/provisioning/`.

---

## 8. C++ Compute Layer

Hot paths (order book, vectorised backtester, risk calculations) implemented in C++20
with nanobind Python bindings. Source in `cpp/`. Build: CMake + Conan 2.
See `.cursor/rules/cpp.mdc` for conventions.

---

## 9. Admin Service

_See [docs/admin-service.md](admin-service.md) for full detail._

Jinja2 + htmx + Tailwind, no build step. Accessible on port 8080 over Tailscale.
Confirmation modals required for all mutating actions.

---

## 10. Secrets Management

_See [docs/secrets.md](secrets.md)._
sops + age. Private key in 1Password as "theeyebeta age key". CI uses `SOPS_AGE_KEY` secret.

---

## 11. CI/CD Pipeline

_See [docs/ci.md](ci.md) and `.github/workflows/ci.yml`._

Three jobs: lint → [py-test, py-int, cpp-build, sbom] → all-ok sentinel.
Release workflow: tag `v*.*.*` → build 14 Docker images → publish `tb` CLI → GitHub Release.
Deploy workflow: push to `main` → SSH over Tailscale → `docker compose up` → `tb status`.

---

## 12. Deployment

_See [docs/headless-operations.md](headless-operations.md) §Deploy._

---

## 13. Disaster Recovery

_TODO — document backup schedule, restore procedures, RTO/RPO targets._

---

## 14. Repository Layout

### 14.1 Directory Tree

```
theeyebeta/
├── .claude/
│   ├── rules/                  # Path-scoped AI rules (01-04)
│   └── agents/                 # Subagent specs (dev, infra)
├── .cursor/
│   └── rules/                  # Cursor .mdc rules (5 files)
├── .github/
│   ├── actions/
│   │   ├── setup-uv/           # Composite: Python + uv
│   │   └── docker-setup/       # Composite: Buildx + GHCR login
│   └── workflows/
│       ├── ci.yml              # PR checks (lint, test, cpp-build, sbom)
│       ├── release.yml         # Tag → GHCR images + PyPI + GitHub Release
│       └── deploy.yml          # Push to main → SSH deploy → Mac mini
├── cpp/                        # C++20 source (CMake + Conan)
│   ├── .clang-format           # LLVM style, 100-col
│   └── conanfile.py
├── db/
│   └── migrations/             # Alembic versions (see §4.2)
├── docs/
│   ├── adr/                    # Architecture Decision Records (0001–0007)
│   ├── templates/              # Dockerfile, README, ADR templates
│   ├── architecture.md         # THIS FILE
│   ├── agents.md
│   ├── admin-service.md
│   ├── ci.md
│   ├── data-model.md
│   ├── headless-operations.md
│   ├── repo-layout.md
│   └── secrets.md
├── infra/
│   ├── grafana/provisioning/   # Datasources + dashboards (auto-provisioned)
│   ├── otelcol/                # OTel Collector config
│   ├── postgres/init/          # Extension init SQL
│   ├── prometheus/             # Scrape config
│   └── tempo/                  # Tempo config
├── libs/                       # Shared Python libraries
├── scripts/
│   ├── db-migrate.sh
│   └── decrypt-env.sh
├── secrets/
│   ├── .sops.yaml              # Encryption rules
│   └── dev.enc.yaml            # Encrypted dev secrets (tracked in git)
├── services/                   # 14 application services
│   ├── data-ingestion/
│   ├── snapshot-packager/
│   ├── llm-gateway/
│   ├── agent-runtime/
│   ├── guard-service/
│   ├── master-orchestrator/
│   ├── risk-service/
│   ├── compliance-service/
│   ├── oms/
│   ├── broker-adapter-alpaca/
│   ├── backtest-engine/
│   ├── audit-service/
│   ├── rnd-agent/
│   └── admin-service/
├── tb/                         # tb CLI tool (published as tb-theeyebeta-cli)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── smoke/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .sops.yaml
├── CLAUDE.md
├── CONTRIBUTING.md
├── Makefile
├── README.md
├── cliff.toml
├── docker-compose.yml
└── pyproject.toml              # uv workspace root
```

---

## 15. Operations Runbook

_See [docs/headless-operations.md](headless-operations.md) for the full runbook._

### Quick reference

```bash
# Check system health
tb status

# View logs
tb logs <service-name>
make logs-<service-name>

# Deploy a single service manually
tb deploy <service-name>    # requires confirmation

# Emergency stop
docker compose stop <service-name>

# Full restart
make down && make up

# Rollback to previous commit
cd ~/theeyebeta
git log --oneline -5          # find the good commit
git reset --hard <sha>
docker compose up -d --force-recreate
```
