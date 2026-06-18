# Architecture

> **Status:** Living document — update when the system changes, not after.
> Sections are referenced by CLAUDE.md, .cursor/rules/, and .claude/rules/.
> For a working agent that keeps this file in sync automatically, see the
> `doc-sync` skill (`.claude/skills/doc-sync/SKILL.md`).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Production Host](#2-production-host)
   - [2.1 Hardware](#21-hardware)
   - [2.2 Port Map](#22-port-map)
3. [Service Topology](#3-service-topology)
   - [3.1 Service Inventory](#31-service-inventory)
   - [3.2 Communication Patterns](#32-communication-patterns)
   - [3.3 The Two-Loop Cycle](#33-the-two-loop-cycle)
4. [Data Model](#4-data-model)
   - [4.1 The `theeyebeta` Schema](#41-the-theeyebeta-schema)
   - [4.2 Migration Modules](#42-migration-modules)
   - [4.3 The Shared-Instance Gotcha](#43-the-shared-instance-gotcha)
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

## 1. Overview

theeyebeta is a self-hosted algorithmic-research and market-intelligence platform.
It is **designed** around a two-loop architecture: a fast execution loop (ms → s) driven by live
market data, and a slow research loop (min → h) driven by LLM agents and backtesting. As of this
writing only a fraction of that design is actually running in production — see
[§3.1](#31-service-inventory) for exactly which parts. The rest is real, tested code waiting on a
deploy unit, not vaporware and not stub code.

All services are Python 3.12 / FastAPI, sharing one PostgreSQL 17 instance (+ TimescaleDB +
pgvector), Redis 7, and NATS 2 JetStream. Performance-critical paths use C++20 via nanobind
bindings. The trading-agent LLM backend is OpenAI models (`gpt-5`, `gpt-4o-mini`) reached through
an in-repo LiteLLM proxy — **not** Claude. Claude Code is used as a *development* tool for this
repo (writing/reviewing code) and has no runtime role in the trading system; don't conflate the
two when reading `CLAUDE.md` vs `docs/agents.md`.

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

> Source of truth: `docker-compose.yml` (containerized services) and `deploy/systemd/*` (bare-metal
> units). `infra/systemd/theeyebeta-admin.service` is a stale duplicate — ignore it; the real admin
> unit install path is `deploy/systemd/theeyebeta-admin.service`.

| Service | Port | Runtime | Notes |
|---------|------|---------|-------|
| `data-ingestion` | 7010 | docker-compose | behind `caddy-data-ingestion` (mTLS) |
| `snapshot-packager` | 7011 | systemd (`theeye-snapshot-packager.service`) | also defined in `docker-compose.yml` for dev, but the deployed instance is the bare-metal unit (added 2026-06-18) |
| `llm-gateway` (LiteLLM proxy) | 4000 | docker-compose | behind `caddy-llm-gateway`; config in `config/litellm.yaml` |
| `admin-service` | 7200 | docker-compose | behind `caddy-admin-service`; Tailscale ACL restricts who can reach it (ADR-0011) |
| `agent_runtime` | 8004 | systemd (`theeye-agent-runtime.service`) | only fully-deployed agent worker today |
| `theeyebeta-dataapi` (sibling repo `TheEyeBetaDataAPI`) | 7000 | systemd, **user** unit | not part of this repo's codebase — see [§12](#12-deployment) |
| `master_orchestrator` | 7050 | systemd (`theeye-master-orchestrator.service`) | gates the `risk_metrics` writer |
| `risk_service` | 7060 (gRPC) | code-complete, unit **staged + disabled** (`deploy/systemd/staged/`) | blocked upstream on "0 portfolios" — see `docs/ops/risk-metrics-activation.md` |
| `guard_service` | 7040 (gRPC) / 8005 (HTTP bridge) | code-complete, no deploy unit | |
| `oms` | 7080 | systemd (`theeye-oms.service`) | paper-mode order lifecycle; live trading gated separately (`broker_adapter_alpaca.live_gate`) |
| `broker_adapter_alpaca` | 7090 | systemd (`theeye-broker-adapter-alpaca.service`) | running in paper mode (`BROKER_MODE=paper`); live mode requires DB + Redis approval (`live_gate.py`) |
| `backtest_engine` | 7100 | code-complete, no deploy unit | |
| `audit_service` | 7110 | code-complete, no deploy unit | note: audit_log **writes** are already live via `BaseWorker._finish_completed`, independent of this HTTP service — see §4.3 of `SERVICES_STATUS.md` |
| `compliance_service` | 7070 (gRPC) / 8008 (HTTP bridge) | systemd (`theeye-compliance-service.service`) | |
| `rnd_agent` | 7120 | code-complete, no deploy unit | |
| PostgreSQL 17 + TimescaleDB + pgvector | 5432 | docker-compose | |
| Redis 7 | 6379 | docker-compose | |
| NATS client / monitor | 4222 / 8222 | docker-compose | |
| MinIO S3 API / console | 9000 / 9001 | docker-compose | console exposed beyond loopback |
| Grafana | 3000 | docker-compose | |
| Prometheus | 9090 | docker-compose, `network_mode: host` | |
| Loki | 3100 | docker-compose | |
| Tempo | 3200 | docker-compose | |
| OTel Collector gRPC / HTTP | 4317 / 4318 | docker-compose | |
| Alertmanager / blackbox-exporter | — | docker-compose | see `infra/prometheus/alerts.yml` |

The real **production data pipeline** is not in the table above — it's ~20 timer-driven workers
under `workers/*.py`, installed from `deploy/systemd/theeye-*.{service,timer}` (intraday ingest,
macro + macro-refresh, massive ingest, sector aggregation, market-cap, daily-pipeline,
gap-sentinel, nightly backup, news ingest, heartbeat-monitor, reporting-chain, audit-verify,
latest-snapshot, zinc EOD/EOM/EOQ/EOW/EOY, zinc-tracker). `theeye-supabase-sync` is masked
(broken — queries a missing table, tracked as a product decision). `deploy/systemd/archived/`
holds 4 decommissioned units (`theeyebeta-api`, `-engine`, `-trask`, `-watcher`) — don't resurrect
without checking why they were retired.

---

## 3. Service Topology

### 3.1 Service Inventory

`services/` has 16 directories. **`SERVICES_STATUS.md` is the live source of truth** for what's
deployed vs. scaffolded — read it before assuming any service in this list is actually running.
Summary as of its last snapshot:

- **Deployed:** `admin_service` (docker-compose, :7200), `agent_runtime` (systemd, :8004),
  `snapshot_packager` (systemd, `theeye-snapshot-packager.service`, :7011, added 2026-06-18 —
  writes to MinIO bucket `theeyebeta-snapshots`), `master_orchestrator`, `compliance_service`,
  `oms`, `broker_adapter_alpaca` (all systemd, all running in paper mode), plus the
  `data-ingestion`/`llm-gateway` docker-compose services. The `llm_gateway` service directory is
  config/scripts only — the actual running proxy is the LiteLLM container.
- **Code-complete, not deployed:** `audit_service`, `backtest_engine`, `guard_service`, `rnd_agent`,
  `risk_service` (unit staged but disabled — closest to going live). Every one of these has real
  NATS consumers, settings modules, and tests; "not deployed" means no systemd unit / compose
  entry, not "unfinished stub."
  `services/api/` and `services/worker/` are genuinely empty placeholders — the live external API
  is the **separate sibling repo** `TheEyeBetaDataAPI`, not this repo.

### 3.2 Communication Patterns

| Pattern | Used for | Technology |
|---------|----------|-----------|
| Request/response | Synchronous service calls | HTTP (FastAPI → httpx) |
| Event stream | Market data, fills, signals | NATS JetStream subjects |
| Durable queue | Backtest jobs, research tasks | NATS JetStream consumers |
| Shared state | Order book, positions | PostgreSQL (`theeyebeta` schema) |
| Cache | Rate limits, session state | Redis |
| Object storage | Snapshots, parquet files, models | MinIO |

All of the above are implemented in code (`consumer.py`/`producer.py` modules exist in
`master_orchestrator`, `oms`, `audit_service`, `broker_adapter_alpaca`, `guard_service`,
`agent_runtime`, `rnd_agent`). Whether traffic is actually flowing depends on §3.1 —
`master_orchestrator`, `oms`, and `broker_adapter_alpaca` are live and consuming/publishing today;
`audit_service`, `guard_service`, and `rnd_agent` still have no running process.

### 3.3 The Two-Loop Cycle

_Diagram is embedded in the [README](../README.md#the-two-loop-architecture)._

**Fast loop** (execution, as designed): `data-ingestion` → `agent_runtime` → `guard_service` →
`master_orchestrator` → `risk_service` → `oms` → `broker_adapter_alpaca` → fills back to `oms`.
**`data-ingestion`, `agent_runtime`, `master_orchestrator`, `oms`, and `broker_adapter_alpaca` are
running** (paper mode); `guard_service` and `risk_service` still have no deploy unit, so pre-trade
guard checks and live risk metrics are not yet wired into the loop.

**Slow loop** (research, as designed): `snapshot_packager` → `backtest_engine` → `rnd_agent` →
`llm-gateway` → proposals → `master_orchestrator`. **`snapshot-packager`, `llm-gateway`, and
`master_orchestrator` are running**; backtesting and the R&D agent are not deployed.

The platform's actual day-to-day work is the timer-driven `workers/*` pipeline (§2.2), which is
separate from this two-loop design and does not depend on it.

---

## 4. Data Model

_Full diagnostic detail: [docs/db-state-map.md](db-state-map.md) (generated by
`scripts/diagnose_db_state.py`) and [docs/db-engineer-SKILL.md](db-engineer-SKILL.md)._

### 4.1 The `theeyebeta` Schema

This repo's Alembic project owns exactly **one** schema: `theeyebeta` (39 tables as of the last
scan, ~1 MB — it is young and lightly populated, not because anything is broken, but because most
of the trading-agent pipeline isn't deployed yet per §3.1).

Tables grouped by the migration that introduced them:

| Domain | Migrations | Key tables |
|--------|------------|------------|
| Market reference data | 0001 | `exchanges`, `instruments`, `market_calendars`, `holidays` |
| Prices & corporate actions | 0002 | `prices_daily` (hypertable), `prices_intraday` (hypertable), `corporate_actions` |
| Fundamentals/macro/news | 0003 | `fundamentals`, `macro_indicators` (hypertable), `news_articles`, `news_embeddings` (pgvector, HNSW) |
| Agents & decisions | 0004, 0033, 0035 | `agents` (+ `reports_to` self-FK), `agent_runs`, `agent_decisions`, `agent_messages`, `agent_memory` (pgvector), `agent_reports` |
| Guard rails & proposals | 0005 | `guard_violations`, `proposals` |
| Trading | 0006, 0016, 0027 | `accounts`, `portfolios`, `strategies`, `signals` (hypertable, realigned in 0027), `orders`, `executions`, `positions` |
| Backtesting & risk | 0007 | `backtest_runs`, `backtest_results`, `risk_metrics` (hypertable), `compliance_checks` |
| LLM/API cost tracking | 0008, 0013 | `model_runs`, `api_costs` |
| Audit (append-only) | 0009, 0029, 0030, 0034 | `audit_log` (RANGE-partitioned monthly, hash-chained `prev_hash`/`row_hash`), `audit_checkpoints` (WORM, RLS insert-only), `audit_chain_status` |
| Snapshots | 0010, 0011 | `data_snapshots`, `data_snapshots_packaged` |
| R&D read-only access | 0015 | `system.agent_constitutions` view |
| Universe / market-cap | 0018, 0024 | `market_cap_daily`, `audit_cap_events`, `public_ticker_map` (bridge table — see §4.3) |
| Calendar | 0019 | `trading_calendar` |
| Worker ops | 0020, 0021 | `worker_runs`, `worker_heartbeats`, `trask_components`, `trask_circuit_breakers`, `audit_data_gaps`, `audit_alerts` |
| Technicals/sector | 0022, 0023 | `ind_technical_daily`, `sector_daily` |
| Admin RBAC + MFA | 0026, 0028 | `admin_roles`, `admin_users`, `admin_user_roles`, `prelive_check_cache` |
| Paper fund tracking | 0031, 0032 | `paper_fund_snapshots` (hypertable), seeded paper accounts for ZINC INVESTMENTS / NYSE / NASDAQ portfolios |

**Hypertables:** `prices_daily`, `prices_intraday`, `macro_indicators`, `signals`, `risk_metrics`,
`paper_fund_snapshots`. **pgvector:** `news_embeddings`, `agent_memory` (both `vector(1536)`,
HNSW index). **Roles:** `tb_app` (full DML on operational tables; `audit_log` insert+select only,
no update/delete) and `tb_rnd_readonly` (read-only, plus narrow inserts into `proposals`,
`agent_runs`, `model_runs`, `agent_reports`).

Empty-looking tables (`risk_metrics`, large stretches of `audit_log`) are usually *correct*, not
broken — e.g. `risk_metrics.portfolio_id` is a `NOT NULL` FK and the platform has no live
portfolios/positions yet. Don't "fix" this by writing synthetic rows.

### 4.2 Migration Modules

Migrations are sequential (`0000`–`0035` today), one logical change per file, not one-schema-per-file
as an older draft of this doc implied. See the domain table above for the current mapping; when
adding a migration, extend that table rather than inventing a new schema.

### 4.3 The Shared-Instance Gotcha

**This is the single most important thing for a new engineer to know about the database.** The
same Postgres instance also hosts:

- **`public` schema — 96 GB, 69 tables, actively written**, including `signals` (144M rows),
  `score_audit_log` (20M rows), `trask_audit_events` (26.7M rows), year-partitioned `price_daily_*`
  tables. Its own `alembic_version` (`20260313_02`, date-based) is tracked by **a codebase that has
  not been located** on this machine — it predates this repo and is not safe to migrate, drop, or
  "clean up" from here. Treat it as belonging to a system you cannot see the source of.
- **`iam` schema — small (≈2 MB, 6 tables)**, service auth/identity, owned by yet another system.

Several table names exist in **both** `public` and `theeyebeta` with *completely different
column layouts* — `signals`, `exchanges`, `corporate_actions`, plus the two independent
`alembic_version` tables. Same name, unrelated schema, unrelated data — do not assume a query
against `signals` means `theeyebeta.signals` unless the schema is qualified. The one deliberate
bridge between the two worlds is `theeyebeta.public_ticker_map` (instrument_id ↔ public ticker id,
migration 0024). See `docs/db-state-map.md §4` for the exact column diffs and
`docs/db-engineer-SKILL.md` for the day-to-day rules this implies for any DB-touching change.

---

## 5. LLM & Agent Layer

_See [docs/agents.md](agents.md) for the agent hierarchy and model-routing detail._

Trading-agent LLM traffic runs entirely on OpenAI models (`gpt-5`, `gpt-4o-mini`) via the
LiteLLM proxy (`config/litellm.yaml`) fronted by the `llm-gateway` docker-compose service.
Migration `0035` retired the last Claude model aliases from the agent roster — there is no
Anthropic dependency left in the runtime path.

---

## 6. Security

_See [docs/secrets.md](secrets.md) for secrets management and `docs/adr/0011-network-security.md`
(consolidated from the prior `docs/ADR/` location) for the Tailscale ACL / JWT model._
All services run as non-root in containers. `admin-service` binds all interfaces but is gated by
a Tailscale ACL (`tag:operator` → `tag:server` on 7200/7000/5432/22 only) plus RS256 JWT auth on
`/admin/*`, with MFA (TOTP) required for `MASTER_ADMIN`. Audit log rows are append-only — see §4.1.

---

## 7. Observability

Traces → Tempo, Metrics → Prometheus, Logs → Loki. All via OTel Collector.
Grafana datasources are auto-provisioned with trace ↔ log correlation.
See `infra/grafana/provisioning/` and `infra/prometheus/alerts.yml` for the live alert rules
(service-health-probe-down, critical-service-metrics-missing, high-error-rate, order-flow-latency,
queue-depth, audit-chain-broken).

---

## 8. C++ Compute Layer

Hot paths implemented in C++20 with nanobind Python bindings, exposed as `zinc_native`. Source in
`cpp/`. Build: CMake + Conan 2 (`make build-cpp`). Modules: `risk` (correlation, CVaR, VaR,
drawdown), `ta` (ADX, ATR, Bollinger, HMM, z-score), `opt` (mean-variance, HRP, Black-Litterman),
`bt` (backtest engine), `oms` (position tracking). See `.cursor/rules/cpp.mdc` for conventions.

---

## 9. Admin Service

_See [docs/admin-service.md](admin-service.md) for full detail._

Jinja2 + htmx + Tailwind, no build step. Runs in docker-compose at `:7200` behind Caddy/mTLS,
reachable only via the Tailscale ACL described in §6. Confirmation modals required for all
mutating actions. RBAC roles (`READ_ONLY`/`COMPLIANCE`/`ANALYST`/`OPERATOR`/`MASTER_ADMIN`) are
defined in migration `0026`.

---

## 10. Secrets Management

_See [docs/secrets.md](secrets.md)._
sops + age. Private key in 1Password as "theeyebeta age key". CI uses `SOPS_AGE_KEY` secret.

---

## 11. CI/CD Pipeline

_See [docs/ci.md](ci.md) and `.github/workflows/`._

Five workflows: `ci.yml`, `deploy.yml`, `release.yml`, `paper-smoke.yml`, `bench.yml`.
`ci.yml` job graph: `lint` gates everything; `py-test` → `integration-tests` → `smoke-staging` run
in sequence after `lint`; `cpp-build`, `sbom`, and `docs` run in parallel off `lint`; `all-ok`
requires all seven jobs. There is no Python version matrix — 3.12 is pinned everywhere.
Release workflow: tag `v*.*.*` → build images → publish `tb` CLI → GitHub Release (notes via
git-cliff). Deploy workflow: push to `main` → SSH over Tailscale → `docker compose up` → `tb status`.
`paper-smoke.yml` is a **separate**, nightly (weekday cron), self-hosted-runner workflow that hits
*live* paper-trading endpoints — don't confuse it with the in-CI `smoke-staging` job, which runs
against ephemeral compose infra on every PR.

---

## 12. Deployment

_See [docs/headless-operations.md](headless-operations.md) §Deploy and `deploy/README.md` /
`deploy/MACMINI_OPERATOR_RUNBOOK.md` for the unit-by-unit install commands._

This repo deploys to the Mac mini via `deploy/systemd/*` units and `docker-compose.yml`. The
externally-facing market-data API is **not** part of this repo — it's the sibling repo
`TheEyeBetaDataAPI`, deployed separately as the user unit `theeyebeta-dataapi.service` (:7000).

---

## 13. Disaster Recovery

_See [docs/ops/disaster-recovery.md](ops/disaster-recovery.md) for the full runbook._

- **Backup:** `theeye-backup.timer` runs `scripts/backup_db.sh` (pg_dump) nightly at **02:00 UTC**
  (`deploy/systemd/theeye-backup.timer`).
- **Restore drill:** `scripts/test_restore.sh` — restores into a scratch `theeyebeta_restore_test`
  DB and validates schema + row counts.
- **Targets:** RPO 24 hours (daily backup cadence), RTO 4 hours (manual restore + service restart).
- These targets and the restore procedure cover the `theeyebeta` schema only — the `public`/`iam`
  schemas described in §4.3 belong to a system this repo doesn't own or back up.

---

## 14. Repository Layout

### 14.1 Directory Tree

```
TheEyeBetaProd/
├── .claude/
│   ├── rules/                  # Path-scoped AI rules (01-04 + cpp/frontend/python/sql/tests)
│   ├── agents/                 # Subagent specs (dev, infra)
│   └── skills/                 # doc-sync (this repo's own doc-update skill)
├── .cursor/                    # Cursor IDE rules
├── .github/
│   └── workflows/              # ci.yml, deploy.yml, release.yml, paper-smoke.yml, bench.yml
├── cpp/                        # C++20 source (CMake + Conan); see §8
├── db/
│   ├── migrations/versions/    # Alembic 0000–0035 (see §4)
│   ├── reference/               # universe_v1/v2/eod.txt — instrument universe tiers
│   └── seeds/                   # agents.py, seed_instruments.py, exchanges.sql, strategies.sql, universe.yaml
├── deploy/
│   ├── systemd/                 # the REAL deploy units (workers + service units + timers)
│   │   ├── archived/             # decommissioned units — don't resurrect without checking why
│   │   └── staged/               # built but intentionally not enabled (e.g. risk_service)
│   ├── install_systemd_units.sh
│   └── MACMINI_OPERATOR_RUNBOOK.md
├── docs/
│   ├── adr/                     # Architecture Decision Records (0001–0011)
│   ├── ops/                     # runbooks: disaster-recovery, alerting, secrets, MFA, paper-trading, ...
│   ├── infra/                   # database-roles.md, tailscale-acl-policy.json
│   ├── api/                     # generated OpenAPI specs + ReDoc HTML (`make docs-api`)
│   ├── templates/                # Dockerfile, README, ADR templates
│   ├── architecture.md           # THIS FILE
│   ├── repo-layout.md
│   ├── data-model.md
│   ├── db-state-map.md           # generated diagnostic snapshot — don't hand-edit
│   ├── db-engineer-SKILL.md      # mandatory reading before touching any DB-adjacent code
│   ├── agents.md
│   ├── admin-service.md
│   ├── ci.md
│   └── secrets.md
├── infra/                       # dev-infra config mounted into docker-compose
│   ├── compose/, caddy/, cloudflared/, grafana/, otelcol/, postgres/init/, prometheus/, tempo/
│   ├── systemd/                 # stale duplicate — real units live in deploy/systemd/
│   └── k8s/                     # placeholder only, not in use
├── libs/                        # zinc_native, zinc_proto, zinc_schemas, zinc_test
├── scripts/                     # macro_ingestor/, diagnose_db_state.py, backup_db.sh, prelive_check.py, ...
├── services/                    # 16 dirs — see §3.1 for deployed vs. code-complete status
├── tb/                          # tb CLI (published as tb-theeyebeta-cli)
├── tests/
│   ├── unit/, integration/, smoke/
├── workers/                     # the actual production data pipeline (timer-driven, see §2.2)
├── config/
│   ├── agents/hierarchy.yaml     # agent reports-to tree — see §5
│   └── litellm.yaml              # model routing
├── CLAUDE.md
├── CONTRIBUTING.md
├── README.md
├── SERVICES_STATUS.md            # live deployed/scaffolded snapshot — see §3.1
├── cliff.toml                    # git-cliff CHANGELOG generation
├── docker-compose.yml
└── pyproject.toml                # uv workspace root
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
