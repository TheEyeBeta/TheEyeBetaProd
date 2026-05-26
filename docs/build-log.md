# theeyebeta Build Log

Each line = one prompt completed.
Format: `<prompt-id> <status> <date> [notes]`
Status: ✓ ok · ⚠ manual-fix · ✗ skipped

> **How to update:**
> When a prompt is finished, check the box, add the emoji + date, and append a note to
> **[Lessons Learned](#lessons-learned)** if anything went wrong.

---

## 17.0 Repo Bootstrap

- [x] P-0-01 ✓ 2026-05-22 — Monorepo directory tree + uv workspace (`pyproject.toml`, `members = ["services/*", "libs/*", "tb"]`)
- [x] P-0-02 ✓ 2026-05-22 — `CLAUDE.md` — project-memory for Claude Code (identity, conventions, hard limits, pre-approved commands)
- [x] P-0-03 ✓ 2026-05-22 — Claude rules (`.claude/rules/` — 01-code-style, 02-testing, 03-security, 04-infrastructure, python, cpp, sql, tests, frontend)
- [x] P-0-04 ✓ 2026-05-22 — Cursor rules (`.cursor/rules/` — bootstrap, code-style, cpp, db, frontend-htmx, project, python-fastapi, sql)
- [x] P-0-05 ✓ 2026-05-22 — `README.md` + `CONTRIBUTING.md` (quickstart, service map, two-loop diagram, branch policy, conventional commits)
- [x] P-0-06 ✓ 2026-05-22 — `Makefile` (up/down/nuke, lint, format, test/test-int/test-smoke, build-cpp, db-migrate, decrypt-env, install)
- [x] P-0-07 ✓ 2026-05-22 — `docker-compose.yml` (Postgres/TimescaleDB, Redis, NATS, MinIO, Prometheus, Loki, Tempo, Grafana, OTel Collector — all with healthchecks)
- [x] P-0-08 ✓ 2026-05-22 — `.github/workflows/ci.yml` (lint → py-test → py-int → cpp-build → sbom → all-ok sentinel)
- [x] P-0-09 ✓ 2026-05-22 — `.github/workflows/release.yml` + `deploy.yml` (image build matrix, rolling deploy via `tb`)
- [x] P-0-10 ✓ 2026-05-22 — Pre-commit config (`.pre-commit-config.yaml` — ruff, black, gitleaks, conventional-pre-commit, end-of-file-fixer)
- [x] P-0-11 ✓ 2026-05-22 — Secrets scaffolding (`secrets/dev.enc.yaml.template`, `secrets/prod.enc.yaml.template`, `.sops.yaml`, `age` key workflow)
- [x] P-0-12 ✓ 2026-05-22 — GitHub meta (`.github/CODEOWNERS`, `pull_request_template.md`, branch-protection docs in CONTRIBUTING.md)

---

## 17.1 Database Migrations

- [x] P-DB-01 ✓ 2026-05-22 — `0000_extensions` — TimescaleDB, pgvector, uuid-ossp, pg_trgm; `theeyebeta` schema + `tb_app` / `tb_rnd_readonly` roles
- [x] P-DB-02 ✓ 2026-05-22 — `0001_instruments` — exchanges, instruments (symbol, sector, industry, market, ISIN)
- [x] P-DB-03 ✓ 2026-05-22 — `0002_prices` — OHLCV hypertable + TimescaleDB compression + retention policy
- [x] P-DB-04 ✓ 2026-05-22 — `0003_fundamentals_macro_news` — fundamentals, macro_indicators, news_articles, data_quality_log
- [x] P-DB-05 ✓ 2026-05-22 — `0004_agents` — agent_registry, agent_runs, agent_constitutions (system schema)
- [x] P-DB-06 ✓ 2026-05-22 — `0005_two_loop` — accounts, portfolios, signals, live_trading_approval; two-loop enforcement trigger
- [x] P-DB-07 ✓ 2026-05-22 — `0006_trading` — orders, positions, executions (FK chain: portfolio → instrument → order → execution)
- [x] P-DB-08 ✓ 2026-05-22 — `0007_backtest_risk` — strategies, backtest_runs, backtest_trades, risk_metrics; read grants to tb_rnd_readonly
- [x] P-DB-09 ✓ 2026-05-22 — `0008_costs` — model_runs, api_costs (LiteLLM spend tracking)
- [x] P-DB-10 ✓ 2026-05-22 — `0009_audit` — audit_log (hash-chained, append-only); initial checkpoint row
- [x] P-DB-11 ✓ 2026-05-22 — `0010_data_snapshots` — data_snapshots (NATS event catalog)
- [x] P-DB-12 ✓ 2026-05-22 — `0011_data_snapshots_packaged` — data_snapshots_packaged (MinIO blob catalog)
- [x] P-DB-13 ✓ 2026-05-22 — `0012_litellm_db` — LiteLLM internal tables (verifytoken, spend_logs, team, key, user)
- [x] P-DB-14 ✓ 2026-05-22 — `0013_model_runs_kind` — `kind` column on model_runs (inference / embedding / guard)
- [x] P-DB-15 ✓ 2026-05-22 — `0014_audit_checkpoints` — dedicated audit_checkpoints table + migration of initial row
- [x] P-DB-16 ✓ 2026-05-22 — `0015_rnd_readonly_views` — `system.agent_constitutions` view; tb_rnd_readonly write grants for proposals
- [x] P-DB-17 ✓ 2026-05-22 — `0016_orders_metadata` — `metadata jsonb` column on orders for admin reject reasons
- [x] P-DB-18 ✓ 2026-05-22 — `0017_guard_violations_resolution` — `resolved_by`, `resolved_at`, `note` on guard_violations

---

## 17.2 Shared Libraries

- [x] P-LIB-01 ✓ 2026-05-22 — `zinc_schemas` — Pydantic v2 shared DTOs (PackagedSnapshotV1, broker_base, snapshot_validator, packaged_snapshot)
- [x] P-LIB-02 ✓ 2026-05-22 — `zinc_proto` — protobuf definitions (risk_pb2 — RiskCheckRequest / RiskCheckResponse)
- [x] P-LIB-03 ✓ 2026-05-22 — `zinc_native` — C++20 nanobind extensions (zinc_native.oms state machine, zinc_native.risk kernels — VaR, CVaR, max drawdown)
- [x] P-LIB-04 ⚠ 2026-05-25 — `zinc_test` — pytest plugin (testcontainers fixtures: postgres, redis, nats, minio; alembic_upgraded, seed_data, llm_gateway_mock, alpaca_mock) — see [Lessons Learned §1](#1-zinc_test-parents-index-and-pytest-plugin-double-registration)

---

## 17.3 Data Layer

- [x] P-DATA-01 ✓ 2026-05-22 — `data_ingestion` — OHLCV (yfinance), fundamentals (EDGAR), macro (FRED), news, CN proxy, Alpaca data adapters; APScheduler pipeline; Postgres writer
- [x] P-DATA-02 ✓ 2026-05-22 — `snapshot_packager` — NATS consumer; SnapshotBuilder (instrument universe + prices + fundamentals + news); MinIO upload; NATS publish `snapshots.packaged.*`; schema validation via zinc_schemas

---

## 17.4 Agent & LLM Layer

- [x] P-AGENT-01 ✓ 2026-05-22 — `llm_gateway` — LiteLLM proxy with model routing (Anthropic Claude, OpenAI GPT), rate-limiting, cost logging to Postgres, structlog
- [x] P-AGENT-02 ✓ 2026-05-22 — `agent_runtime` — macro-lead, news-sentiment, technical-analyst agents; NATS consumer; agent_runs persistence; constitution hot-reload
- [x] P-AGENT-03 ✓ 2026-05-22 — `guard_service` — pre-trade signal validation, position limit checks, circuit breakers, guard_violations table; gRPC interface
- [x] P-AGENT-04 ✓ 2026-05-22 — `master_orchestrator` — market-trio workflow (spawn 3 agents → optional debate → synthesise ticket); Redis idempotency lock (`orchestrator:trio:{market}:{date}`); risk + compliance gating; order insert + NATS publish
- [x] P-AGENT-05 ✓ 2026-05-22 — `rnd_agent` — nightly research pipeline; proposal generation; tb_rnd_readonly DB role; LLM prompt templates
- [x] P-AGENT-06 ✓ 2026-05-22 — Agent constitutions (`agents/` markdown files — macro-lead, news-sentiment, technical-analyst, master-orchestrator, rnd; domain agents in client/, compliance/, dev/, finance/, legal/, markets/, research/)

---

## 17.5 Risk & Compliance

- [x] P-RISK-01 ✓ 2026-05-22 — `risk_service` — portfolio VaR (95%), CVaR, max drawdown, HHI, sector/cluster concentration; mandate validation; risk_metrics persistence; gRPC + REST; zinc_native.risk bindings
- [x] P-RISK-02 ✓ 2026-05-22 — `compliance_service` — regulatory rule checks (position limits, wash-trade, short-sale); audit_log writes; NATS consumer

---

## 17.6 Order Management & Execution

- [x] P-TRADE-01 ✓ 2026-05-22 — `oms` — order lifecycle state machine (zinc_native.oms); approve / submit / fill / cancel transitions; ReconciliationLoop; SubmissionGate (Redis pause); NATS fill consumer
- [x] P-TRADE-02 ✓ 2026-05-22 — `broker_adapter_alpaca` — Alpaca paper + live TradingClient; market order submission; TradingStream WebSocket fill handler; NATS approved-order consumer; live-trading gate (DB approval required)
- [x] P-TRADE-03 ✓ 2026-05-22 — `backtest_engine` — vectorised backtester; MinIO snapshot reader; strategy execution; backtest_runs + backtest_trades persistence; Sharpe / drawdown metrics

---

## 17.7 Operations & Observability

- [x] P-OPS-01 ✓ 2026-05-22 — `audit_service` — hash-chained audit_log (SHA-256 chain); WORM checkpoint pinning; `/audit/verify` endpoint; nightly WORM export; NATS event consumer
- [x] P-OPS-02 ✓ 2026-05-22 — `admin_service` — Jinja2/htmx dashboard (orders, agents, guard violations, backtest runs, API costs, proposals, SQL sandbox, services health); JWT auth; rate-limiting; Docker socket integration
- [x] P-OPS-03 ✓ 2026-05-22 — `tb` CLI — `tb status` / `tb logs <svc>` / `tb deploy <svc>` / `tb restart <svc>` / `tb backtest run <id>`; process supervisor; Tailscale-aware
- [x] P-OPS-04 ✓ 2026-05-22 — Grafana dashboards + Prometheus alerting (infra/grafana/provisioning, infra/prometheus/prometheus.yml, alertmanager config)
- [x] P-OPS-05 ✓ 2026-05-22 — OTel Collector pipeline (infra/otelcol.yaml — OTLP → Tempo traces, Prometheus metrics, Loki logs)
- [ ] P-OPS-06 ✗ — `worker` — placeholder only; Celery/ARQ worker not yet implemented

---

## 17.8 Architecture Decisions

- [x] P-ADR-01 ✓ 2026-05-22 — ADR-0001: PostgreSQL + TimescaleDB + pgvector (time-series + vector search in one DB)
- [x] P-ADR-02 ✓ 2026-05-22 — ADR-0001-b: public-schema bridge (SECURITY DEFINER shims for LiteLLM cross-schema access)
- [x] P-ADR-03 ✓ 2026-05-22 — ADR-0002: NATS JetStream over Kafka (lower ops overhead for on-prem single-node)
- [x] P-ADR-04 ✓ 2026-05-22 — ADR-0002-b: data-ingestion ownership (single service owns all market data writes)
- [x] P-ADR-05 ✓ 2026-05-22 — ADR-0003: LiteLLM gateway (unified model routing, cost accounting, rate limits)
- [x] P-ADR-06 ✓ 2026-05-22 — ADR-0004: nanobind over pybind11 (C++20, ABI stability, smaller binaries)
- [x] P-ADR-07 ✓ 2026-05-22 — ADR-0005: sops + age secrets (no Vault dependency, works offline, 1Password distribution)
- [x] P-ADR-08 ✓ 2026-05-22 — ADR-0006: monorepo + plain Make (uv workspace, no Nx/Turborepo overhead)
- [x] P-ADR-09 ✓ 2026-05-22 — ADR-0007: three-model LLM allocation (Opus for synthesis, Sonnet for agents, Haiku for guard)
- [x] P-ADR-10 ✓ 2026-05-22 — ADR-0008: two-loop architecture (fast execution loop ms→s, slow research loop min→h)
- [x] P-ADR-11 ✓ 2026-05-22 — ADR-0009: htmx admin frontend (no SPA build step, server-rendered, Tailwind CDN)
- [x] P-ADR-12 ✓ 2026-05-22 — ADR-0010: Cloudflare + Tailscale dual-access (Cloudflare for public `/admin`, Tailscale for Grafana/MinIO)

---

## 17.9 Testing

- [x] P-TST-01 ⚠ 2026-05-25 — `zinc_test` shared testcontainer fixtures (postgres, redis, nats, minio, alembic_upgraded, seed_data, llm_gateway_mock, alpaca_mock); updated 6 service conftests — see [Lessons Learned §1](#1-zinc_test-parents-index-and-pytest-plugin-double-registration)
- [x] P-TST-02 ✓ 2026-05-25 — Paper smoke test (`tests/e2e/test_paper_smoke.py` — 9-step Alpaca paper pipeline; `paper-smoke.yml` nightly cron; graduation criterion: 7 consecutive nights)

---

## 17.10 Documentation

- [x] P-DOC-01 ⚠ 2026-05-25 — API docs (`scripts/dump_openapi.py`, `make docs-api` ReDoc HTML, `make docs-api-check` CI staleness guard) — see [Lessons Learned §2](#2-p-doc-01-main_api-absent--oms-dummy-database_url)
- [x] P-DOC-02 ✓ 2026-05-25 — Build log (`docs/build-log.md` — this file)

---

## 17.11 API Gateway

- [x] P-AG-01 ⚠ 2026-05-22 — API gateway route catalog (`docs/api-gateway.md` — P-AG-01 route audit, non-overlap analysis, `/admin/*` namespace) — see [Lessons Learned §3](#3-p-ag-01-main_api-not-scaffolded)

---

## 17.12 Broker Adapter — Alpaca

- [x] P-BA-01 ✓ 2026-05-22 — `broker_adapter_alpaca` — Alpaca paper + live `TradingClient`; `SubmitOrderRequest` adapter implementing `BrokerAdapter` Protocol from `zinc_schemas.broker_base`; `streamer.py` WebSocket fill handler; `live_gate.py` hard refusal without `metadata.live_approval=true`

---

## 17.13 Backtest Engine

- [x] P-BT-01 ✓ 2026-05-22 — `backtest_engine` FastAPI on 7100 — vectorised backtester wrapping `zinc_native.bt.Engine`; MinIO snapshot reader; `backtest_runs` + `backtest_trades` persistence; Sharpe / drawdown metrics
- [x] P-BT-02 ✓ 2026-05-22 — Validation harness — `tests/test_validation.py` covers no-look-ahead (3 variants), survivorship-bias (delisted-instrument universe trim), and live-week PnL reconciliation within 1 bp; gate documented in `docs/backtest-validation.md`

---

## 17.14 Audit Service

- [x] P-AU-01 ✓ 2026-05-22 — `audit_service` FastAPI on 7110 — `chain.py:compute_row_hash(prev_hash, payload)` SHA-256 chain; `export.py` Ed25519 WORM signing via `cryptography.hazmat`; `GET /audit/verify` endpoint; nightly WORM export consumer

---

## 17.15 API Gateway Preservation

- [x] P-AG-01 ⚠ 2026-05-22 — `docs/api-gateway.md` — route catalog separating `:7000` (external main API in sibling `TheEyeBetaDataAPI` repo) from `:7200` (`/admin/*` namespace owned by `admin_service`) — see [Lessons Learned §3](#3-p-ag-01-main_api-not-scaffolded)

---

## 17.16 R&D Agent

- [x] P-RND-01 ✓ 2026-05-22 — Constitution + forbidden-targets — `agents/rnd/rnd_agent.agent.md` declares `forbidden_targets: [audit_log, proposals, guard_violations, mandate]`
- [x] P-RND-02 ✓ 2026-05-22 — `rnd_agent` service — startup `probe.py` verifies `tb_rnd_readonly` cannot read/write forbidden tables; `runner.py` UTC 09:00 cron (`run_cron_hour=9`); `db.insert_proposals()` writes to `theeyebeta.proposals`

---

## 17.17 Admin Service — Backend

- [x] P-AD-01 ✓ 2026-05-25 — Service skeleton — FastAPI on 7200 (binds `0.0.0.0` for Tailscale), JWT RS256 auth, slowapi rate limiter (100/min default), refresh-token rotation in Redis, CORS for Cloudflare + Tailscale origins
- [x] P-AD-R-orders ✓ 2026-05-25 — Orders router — `GET /admin/orders/pending`, `GET /admin/orders/{id}`, `POST /admin/orders/{id}/approve`, `POST /admin/orders/{id}/reject` with idempotency keys + audit log writes
- [x] P-AD-R-audit ✓ 2026-05-25 — Audit router — `GET /admin/audit/log` (paginated, filters), proxied `GET /admin/audit/verify`, `GET /admin/audit/checkpoints`
- [x] P-AD-R-agents ✓ 2026-05-25 — Agents router — `GET /admin/agents`, `GET /admin/agents/{id}/runs` (limit=50), `POST /admin/agents/{id}/run` (proxy to `agent-runtime`), `GET /admin/agents/{id}/constitution`
- [x] P-AD-R-guard ✓ 2026-05-25 — Guard router — `GET /admin/guard/violations` (filters: agent_id, severity, unresolved_only), `POST /admin/guard/violations/{id}/resolve`
- [x] P-AD-R-services ✓ 2026-05-25 — Services router — `GET /admin/services/status` (Docker SDK), `POST /admin/services/{name}/restart` (whitelisted services only)
- [x] P-AD-R-backtest ✓ 2026-05-25 — Backtest router — `POST /admin/backtest` publishes `backtests.requested` on NATS; `GET /admin/backtest/{id}/results`; `GET /admin/backtest` (list recent)
- [x] P-AD-R-costs ✓ 2026-05-25 — Costs router — `GET /admin/costs/daily?days=30`, `GET /admin/costs/by-agent?month=YYYY-MM`
- [x] P-AD-R-sql ✓ 2026-05-25 — SQL router — read-only `POST /admin/sql/query` (`sqlparse` `SELECT`-only validator); write-with-confirmation `POST /admin/sql/execute` (`X-Confirm: true` + `X-Idempotency-Key`)
- [x] P-AD-R-proposals ✓ 2026-05-25 — Proposals router — `GET /admin/proposals` (filters), detail / approve / reject endpoints; approve optionally publishes `backtests.requested` for validation
- [x] P-AD-LOAD ⚠ 2026-05-25 — Load test + access checklist — in-process locust harness `tests/test_load.py` + k6 script + Cloudflare/Tailscale checklist in `docs/admin-service.md`. SLO: p99 < 500 ms on `GET /admin/orders/pending`. **Production execution pending on Mac mini host.**

---

## 17.18 Admin Service — Frontend

- [x] P-FE-00 ✓ 2026-05-25 — Base layout — `templates/base.html`, `_nav.html`, `_modal.html`; Tailwind / htmx / Chart.js CDNs; dark-mode toggle; JWT cookie + HX-Redirect handling; severity-colour CSS (`.severity-low/.medium/.high/.critical`)
- [x] P-FE-dashboard ✓ 2026-05-25 — `/admin/` page — 4 stat cards (pending orders, active agents, today's cost, last audit verify); Run Daily Backtest + Verify Audit Chain quick actions; embedded Grafana iframe
- [x] P-FE-orders ✓ 2026-05-25 — `/admin/orders` page — pending-order table with click-to-expand agent rationale; approve (direct row swap) + reject (modal with reason)
- [x] P-FE-audit ✓ 2026-05-25 — `/admin/audit` page — filter form (entity, actor, since, limit), paginated table, "Verify Chain" with inline colour-coded result
- [x] P-FE-agents ✓ 2026-05-25 — `/admin/agents` page — two-pane layout (agents list + detail panel); runs / constitution swap tabs; "Run Now" modal; `highlight.js`-rendered constitution markdown
- [x] P-FE-violations ✓ 2026-05-25 — `/admin/violations` page — severity-coloured rows; filter form (agent_id, severity, unresolved_only=default); click-to-expand JSON detail; resolve modal
- [x] P-FE-costs ✓ 2026-05-25 — `/admin/costs` page — daily stacked bar chart + per-agent doughnut; month-to-date tables by vendor and agent; Chart.js instances rebuild after htmx swaps
- [x] P-FE-sql ✓ 2026-05-25 — `/admin/sql` page — CodeMirror 5 SQL editor; read/write radio toggle; write-confirmation modal requiring the phrase `I UNDERSTAND` + server-minted UUIDv7 idempotency key
- [x] P-FE-proposals ✓ 2026-05-25 — `/admin/proposals` page — pending/approved/rejected tabs + category filter; markdown-it-rendered rationale; evidence links deep-link to backtest results; approve modal triggers a validation backtest with progress polling; `sessionStorage`-backed defer state
- [x] P-FE-FINAL ⚠ 2026-05-25 — Playwright + axe-core e2e suite — `services/admin_service/tests/test_frontend.py` (`@pytest.mark.frontend`); spins a real uvicorn in a background thread; mints RS256 keypair + bcrypt hash for the real login flow; one htmx swap per page; axe-core asserts 0 critical WCAG 2.0/2.1 A+AA violations. **Browser execution pending on a dev box with `playwright install chromium`.**

---

## 17.19 Per-Agent Constitutions

All 30 `.agent.md` files now load via `load_constitution()` rglob `*.agent.md` (was 24 at audit time on 2026-05-25):

- [x] P-AGT-top-01 ✓ 2026-05-22 — `agents/top/master-orchestrator.agent.md` (orphan duplicate at `agents/master-orchestrator.md` removed 2026-05-26)
- [x] P-AGT-markets-01 ✓ 2026-05-22 — `agents/markets/markets-lead.agent.md`
- [x] P-AGT-markets-02 ✓ 2026-05-26 — `agents/markets/macro-lead.agent.md` (renamed/moved from `agents/macro-lead.md` — wrong-extension drift fix per audit 17.19)
- [x] P-AGT-markets-03 ✓ 2026-05-26 — `agents/markets/news-sentiment.agent.md` (renamed/moved from `agents/news-sentiment.md`)
- [x] P-AGT-markets-04 ✓ 2026-05-26 — `agents/markets/geopolitical-risk.agent.md` (newly authored — was missing per audit 17.19)
- [x] P-AGT-markets-05 ✓ 2026-05-26 — `agents/markets/liquidity.agent.md` (newly authored — was missing)
- [x] P-AGT-research-01 ✓ 2026-05-25 — `agents/research/quant-lead.agent.md`
- [x] P-AGT-research-02 ✓ 2026-05-25 — `agents/research/alpha-mining.agent.md`
- [x] P-AGT-research-03 ✓ 2026-05-25 — `agents/research/backtesting.agent.md`
- [x] P-AGT-research-04 ✓ 2026-05-25 — `agents/research/risk-modeling.agent.md`
- [x] P-AGT-research-05 ✓ 2026-05-25 — `agents/research/factor-research.agent.md`
- [x] P-AGT-research-06 ✓ 2026-05-26 — `agents/research/technical-analyst.agent.md` (renamed/moved from `agents/technical-analyst.md`)
- [x] P-AGT-finance-01 ✓ 2026-05-25 — `agents/finance/finance.agent.md`
- [x] P-AGT-finance-02 ✓ 2026-05-25 — `agents/finance/api-cost-tracker.agent.md`
- [x] P-AGT-finance-03 ✓ 2026-05-25 — `agents/finance/compute-cost-analyzer.agent.md`
- [x] P-AGT-compliance-01 ✓ 2026-05-25 — `agents/compliance/compliance-lead.agent.md`
- [x] P-AGT-compliance-02 ✓ 2026-05-25 — `agents/compliance/pretrade-compliance.agent.md`
- [x] P-AGT-compliance-03 ✓ 2026-05-25 — `agents/compliance/aml.agent.md`
- [x] P-AGT-compliance-04 ✓ 2026-05-25 — `agents/compliance/audit-logging.agent.md`
- [x] P-AGT-legal-01 ✓ 2026-05-25 — `agents/legal/legal-lead.agent.md`
- [x] P-AGT-legal-02 ✓ 2026-05-25 — `agents/legal/contract-analysis.agent.md`
- [x] P-AGT-legal-03 ✓ 2026-05-25 — `agents/legal/regulatory-change.agent.md`
- [x] P-AGT-client-01 ✓ 2026-05-26 — `agents/client/client-lead.agent.md` (newly authored — was missing per audit 17.19)
- [x] P-AGT-client-02 ✓ 2026-05-25 — `agents/client/client-reporting.agent.md`
- [x] P-AGT-client-03 ✓ 2026-05-25 — `agents/client/onboarding.agent.md`
- [x] P-AGT-dev-01 ✓ 2026-05-25 — `agents/dev/tech-lead.agent.md`
- [x] P-AGT-dev-02 ✓ 2026-05-25 — `agents/dev/code-generation.agent.md`
- [x] P-AGT-dev-03 ✓ 2026-05-25 — `agents/dev/code-review.agent.md`
- [x] P-AGT-dev-04 ✓ 2026-05-25 — `agents/dev/devops.agent.md`
- [x] P-AGT-rnd-01 ✓ 2026-05-22 — `agents/rnd/rnd_agent.agent.md` (forbidden_targets: audit_log, proposals, guard_violations, mandate)

See [Lessons Learned §4](#4-p-agt-1719-extension-and-location-drift) for the wrong-extension drift root cause.

---

## 17.20 Cloudflare / Tailscale / Systemd

- [x] P-NET-01 ⏭ 2026-05-22 — `infra/cloudflared/config.yml` — Cloudflare tunnel routing `admin.theeyebeta.store` → `127.0.0.1:7200` (verification on Linux host)
- [x] P-NET-02 ✓ 2026-05-22 — DNS — `admin.theeyebeta.store` resolves to Cloudflare anycast (`172.67.141.201`, `104.21.41.27`)
- [x] P-NET-03 ⏭ 2026-05-22 — Tailscale — `theeyebeta-mac` MagicDNS record for in-tailnet `:7200` access (verified on the Mac mini)
- [x] P-NET-04 ⏭ 2026-05-22 — Systemd — `/etc/systemd/system/theeyebeta.service` runs `tb up` under the operator account on the Mac mini

---

## 17.21 CI/CD

- [x] P-CI-01 ✓ 2026-05-22 — `.github/CODEOWNERS` — Solo-operator default ownership; service-specific reviewers can be added later
- [x] P-CI-02 ✓ 2026-05-22 — `renovate.json` — Schedule "before 6am on monday"; patch updates auto-merge; anthropic/openai/litellm/alpaca packages require manual review

---

## 17.22 Observability

- [x] P-OBS-01 ✓ 2026-05-22 — Grafana dashboards — `infra/grafana/dashboards/{overview,services,agents,orders,costs,audit,ingestion,risk}.json` provisioned via `infra/grafana/provisioning/dashboards/dashboards.yaml`
- [x] P-OBS-02 ✓ 2026-05-22 — Prometheus alerts — `infra/prometheus/alerts.yml` with `HighErrorRate`, `ServiceDown`, `AuditChainBroken`, `PortfolioDrawdown15pct`, `LLMCostSpike`, `ReconciliationDrift`, `GuardViolationsHigh`

---

## 17.23 Security Hardening

- [x] P-SEC-01 ✓ 2026-05-22 — `infra/caddy/Caddyfile` — TLS termination + reverse proxy in front of admin / Grafana
- [x] P-SEC-02 ✓ 2026-05-22 — `docs/security.md` — threat model, secret management, network boundaries
- [x] P-SEC-03 ✓ 2026-05-22 — `scripts/rotate_secrets.sh` + `docs/secret-rotation.md` — sops + age rotation workflow

---

## 17.24 Testing Infrastructure

- [x] P-TST-01 ⚠ 2026-05-25 — `libs/zinc_test/` — pytest plugin (testcontainers fixtures: `postgres_container`, `redis_container`, `nats_container`, `minio_container`, `alembic_upgraded`, seed_data, `llm_gateway_mock`, `alpaca_mock`); workspace member; `pytest11` entry-point — see [Lessons Learned §1](#1-zinc_test-parents-index-and-pytest-plugin-double-registration)
- [x] P-TST-02 ✓ 2026-05-25 — Paper smoke + nightly cron — `tests/e2e/test_paper_smoke.py` (9-step Alpaca paper pipeline); `.github/workflows/paper-smoke.yml` (`cron "0 6 * * 1-5"`); `.github/workflows/bench.yml` (`cron "0 3 * * *"`); graduation criterion: 7 consecutive nights green

---

## 17.25 Documentation

- [x] P-DOC-01 ⚠ 2026-05-25 — API docs — `scripts/dump_openapi.py` + `make docs-api` ReDoc HTML + `make docs-api-check` CI staleness guard. Currently dumps `admin.openapi.json` and `oms.openapi.json`; `main.openapi.json` deferred until `services/main_api/` is migrated from `TheEyeBetaDataAPI` — see [Lessons Learned §2](#2-p-doc-01-main_api-absent--oms-dummy-database_url)
- [x] P-DOC-02 ✓ 2026-05-25 — Build log — `docs/build-log.md` (this file)
- [x] P-DOC-03 ✓ 2026-05-26 — `CHANGELOG.md` (Keep-a-Changelog + Conventional-Commits) covering every P-AD-* + P-FE-* phase plus pending manual verifications

---

## Lessons Learned

Append one note per problematic prompt. Format: `### N. P-XX-NN title` → what broke → root cause → fix applied.

---

### 1. zinc_test: parents index and pytest plugin double-registration

**Prompt:** P-LIB-04 / P-TST-01 (same work)
**Date:** 2026-05-25

**What broke (× 2 bugs):**

1. `_REPO_ROOT = Path(__file__).resolve().parents[5]` in `libs/zinc_test/src/zinc_test/_infra.py`
   resolved to a non-existent ancestor instead of the repo root.
   **Root cause:** miscounted path depth. The file lives at
   `libs/zinc_test/src/zinc_test/_infra.py` → parents[0] = `zinc_test/`,
   [1] = `src/`, [2] = `libs/zinc_test/`, [3] = `libs/`, **[4] = repo root**.
   **Fix:** changed `parents[5]` → `parents[4]`.

2. `services/admin_service/tests/conftest.py` originally included
   `pytest_plugins = ["zinc_test.plugin"]`.  
   Once `uv sync` installed `zinc-test` with its `pytest11` entry-point
   (`zinc_test = "zinc_test.plugin"` in pyproject.toml), pluggy registered the
   module under two different names and raised
   `Plugin already registered under a different name`.  
   **Root cause:** entry-point auto-registration + explicit `pytest_plugins`
   declaration are mutually exclusive for the same module.  
   **Fix:** removed the explicit `pytest_plugins` line from `admin_service/tests/conftest.py`
   and added a comment explaining why (mirrors the comment already in that conftest).

---

### 2. P-DOC-01: main_api absent + OMS dummy DATABASE_URL

**Prompt:** P-DOC-01
**Date:** 2026-05-25

**What broke (× 2 issues):**

1. The prompt specified `from services.main_api.main import app`.
   `services/main_api/` does not exist in this repo — per `docs/api-gateway.md`,
   the main external API lives in the sibling `TheEyeBetaDataAPI` repository.
   **Fix:** substituted OMS (`services/oms`) as the "main API" surrogate; documented
   the gap in `scripts/dump_openapi.py` and the Makefile comment.
   When `services/main_api/` is migrated here, add `_dump_main_api()` and
   a third entry to `_SERVICES` in the dump script.

2. `oms.settings.Settings.pg_dsn()` raises `OSError("DATABASE_URL must be set")`
   when the field is empty — even in the `create_app()` constructor
   (before the lifespan starts).
   **Fix:** `os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost/dummy")`
   in `_dump_oms()` before importing the OMS module. The dummy DSN is syntactically
   valid but never dialled because `create_app()` only stores the DSN; actual pool
   creation happens inside the ASGI lifespan.

---

### 3. P-AG-01: main_api not scaffolded

**Prompt:** P-AG-01
**Date:** 2026-05-22 (bootstrap)

**Context:** `docs/api-gateway.md` was written as a route-audit document (P-AG-01
task: "preserve existing :7000 routes, document separation from admin-service on :7200").
The main API service at port 7000 was confirmed to live in `TheEyeBetaDataAPI`;
`services/api/` was created as an empty placeholder only.

**Impact:** `make docs-api` generates docs for OMS instead of the real main API.
CI `docs-api-check` will fail if the main API is ever migrated in without updating
`scripts/dump_openapi.py`.

**Mitigation:** see Lessons Learned §2. When migration happens:
```bash
# 1. Scaffold the service
bash scripts/new_service.sh main_api

# 2. Add _dump_main_api() to scripts/dump_openapi.py

# 3. Add to Makefile docs-api and check_openapi.sh

# 4. Run make docs-api and commit docs/api/main.openapi.json
```

---

### 4. P-AGT-* (17.19): extension and location drift

**Prompts:** P-AGT-markets-{02..05}, P-AGT-research-06, P-AGT-client-01
**Date detected:** 2026-05-25 (build audit)
**Date fixed:** 2026-05-26

**What broke:**

The build audit run on `b00903b` flagged **6 of 30 agent constitutions** as
non-loadable by `agent_runtime.constitution.load_constitution()`:

| Issue | Files |
|-------|-------|
| Wrong extension (`.md` not `.agent.md`) | `agents/macro-lead.md`, `agents/news-sentiment.md`, `agents/technical-analyst.md` |
| Missing entirely | `geopolitical-risk`, `liquidity`, `client-lead` |
| Orphan loose-file duplicate | `agents/master-orchestrator.md` (canonical at `agents/top/master-orchestrator.agent.md`) |

**Root cause:** `load_constitution()` uses `Path.rglob("*.agent.md")`. Files at
the `agents/` root with a `.md` (not `.agent.md`) suffix were silently ignored,
which masked the gaps because `len(loaded) == 24` looked plausible for a
"24 + R&D" agent count target. The audit's explicit comparison against the
markets/client trio definitions surfaced the missing files.

**Fix applied:**

1. Renamed and moved the three wrong-extension files to their canonical
   department subdirectory with the `.agent.md` suffix:
   - `agents/macro-lead.md` → `agents/markets/macro-lead.agent.md`
   - `agents/news-sentiment.md` → `agents/markets/news-sentiment.agent.md`
   - `agents/technical-analyst.md` → `agents/research/technical-analyst.agent.md`
2. Authored the three missing constitutions
   (`agents/markets/geopolitical-risk.agent.md`,
   `agents/markets/liquidity.agent.md`, `agents/client/client-lead.agent.md`)
   with the standard frontmatter (`agent_id`, `name`, `description`, `model`,
   `max_turns`, `output_schema_version`, `tools`) and body sections (Role,
   Inputs, Outputs, Hallucination Constraints, Math, Style).
3. Deleted the orphan `agents/master-orchestrator.md` duplicate.

**Verification:** `Get-ChildItem -Path agents -Recurse -Filter *.agent.md`
returns **30** files. `load_constitution()` will load all of them.

**Prevention:** consider adding a `pytest -m unit` test in
`services/agent_runtime/tests/test_constitution_set.py` that asserts
`len(loaded) >= 30` and that the set of `agent_id` values matches a
canonical reference list defined in code, so future drift fails CI rather
than waiting for the next audit.
