# TheEyeBeta Backend → Bloomberg-Terminal Frontend Control Map

**Audit date:** 2026-06-15  
**Auditor stance:** Production fintech system. No hand-waving.  
**Critical reality check:** This repo is a **data + research platform in production**, with a **trading/agent stack mostly scaffolded and undeployed** (`SERVICES_STATUS.md`). The existing admin UI (`services/admin_service`, port 7200) covers ~15% of backend capability. The `tb` CLI is the real operator console today.

---

## PHASE 1 — Repository Inventory

### Top-level map (869 files)

| Path | Type | Responsibility | Frontend relevance |
|------|------|----------------|-------------------|
| `services/` | 16 deployable services | FastAPI/gRPC apps | Primary API surface for terminal |
| `workers/` | 13 workers + 10 support modules | Scheduled data pipelines | **No UI** — CLI/systemd only |
| `tb/` | Typer CLI | Operator console (60+ commands) | Must become command palette |
| `db/migrations/` | Alembic | `theeyebeta` schema (47 tables) | SQL playground partial exposure |
| `cpp/` | C++20 + nanobind | Risk, TA, opt, backtest, OMS hot paths | Invisible — needs metrics/API |
| `libs/` | 4 packages | Schemas, native bindings, proto, test fixtures | DTO source for API contracts |
| `agents/` | 58 `*.agent.md` | Agent constitutions (not all wired) | Partial — agents page only |
| `infra/` | Compose, Grafana, systemd | Observability + deploy | Grafana iframe only |
| `deploy/systemd/` | Timers + units | Production schedulers | **No UI control** |
| `scripts/` | 30+ ops scripts | Backfill, migrate, prelive, macro | **No UI** |
| `tests/` | unit/integration/smoke/e2e | Quality gates | CI only |
| `docs/` | Architecture, ADRs, OpenAPI | Spec vs code diverges in places | Source of truth gaps |
| `config/` | `litellm.yaml` | LLM routing | **No UI** |
| `secrets/` | sops templates | Encrypted secrets | CLI `tb secrets` only |

---

### Services inventory (file-by-file responsibility)

#### `services/admin_service/` — **ONLY production-facing control plane**

| File | Symbols | DB / external | Auth | Frontend today |
|------|---------|---------------|------|----------------|
| `main.py` | `create_app()`, `/admin/health` | PG, NATS, Redis | JWT except health | Shell |
| `auth.py` | `login`, `refresh`, `logout`, `get_current_user` | Redis refresh store | RS256 JWT | **No login page** |
| `deps.py` | `get_db`, `get_nats`, `get_redis` | Pool 1–10 | — | — |
| `settings.py` | `Settings` | Env URLs for audit/agent/backtest | — | — |
| `api/orders.py` | pending/approve/reject | `orders`, NATS `orders.approved.*` | JWT | Orders page ✓ |
| `api/audit.py` | log/verify/checkpoints | `audit_log`, audit-service | JWT | Audit page ✓ |
| `api/agents.py` | list/runs/run/constitution | `agents`, agent-runtime :8004 | JWT | Agents page ✓ |
| `api/guard.py` | violations/resolve | `guard_violations` | JWT | Violations page ✓ |
| `api/services.py` | status/restart | **systemctl** (4 units only) | JWT | **JSON only, no page** |
| `api/backtest.py` | list/start/results | backtest-engine :7100 | JWT | Dashboard button only |
| `api/costs.py` | daily/by-agent | `model_runs`, `api_costs` | JWT | Costs page ✓ |
| `api/sql.py` | query/execute | PG (blocks audit/proposals) | JWT + confirm headers | SQL page ✓ |
| `api/proposals.py` | list/approve/reject | `proposals`, NATS backtests | JWT | Proposals page ✓ |
| `api/views.py` | All htmx HTML routes | In-process helpers | JWT | 8 pages |
| `web.py` | Static, nav, layout check | — | JWT | Nav shell |
| `templates/*.html` | Jinja + htmx | — | — | Dense but narrow |

**External deps:** asyncpg, NATS, Redis, httpx → audit-service, agent-runtime, backtest-engine, sudo systemctl.

**Security gaps:** Single operator (`ADMIN_USERNAME`), no RBAC, no `MASTER_ADMIN` role in DB or JWT claims.

---

#### `services/data_ingestion/` — **Optional service; workers do the real work**

| File | Role |
|------|------|
| `main.py` | `GET /health`, `/metrics`, `/metrics/state`, `POST /ingest/run` (HTTP Basic) |
| `pipeline.py` | Publishes NATS `data.snapshots.{market}.{date}` |
| `adapters/fred.py`, `yfinance.py` | FRED/yfinance fetch |
| `writers/postgres_writer.py` | `prices_daily`, `prices_intraday`, `macro_indicators`, `news_*`, `fundamentals` |
| `cli.py` | `tb-ingest` Typer CLI |

**Status:** Not deployed as service. Timers + workers handle ingestion.

---

#### `services/snapshot_packager/` — **Undeployed**

| File | Role |
|------|------|
| `main.py` | `POST /snapshots/build`, metrics |
| `consumer.py` | NATS `data.snapshots.>` → build → publish `snapshots.packaged.*` |
| `builder.py` | Assembles packaged snapshot from PG + MinIO |
| `cli.py` | `tb-snapshot` |

**DB:** `data_snapshots_packaged`, reads prices/fundamentals/news.

---

#### `services/agent_runtime/` — **Undeployed**

| File | Role |
|------|------|
| `main.py` | `POST /agents/{id}/run`, metrics |
| `runner.py` | Executes agent, writes `agent_runs`, `agent_decisions`, publishes `agents.decisions.{id}` |
| `guard_client.py` | Calls guard-service gRPC |
| `math_tool.py` | C++ stats via zinc_native |
| `cli.py` | `tb-agent` |

**58 agent markdown files exist; runtime loads from `theeyebeta.agents` table.**

---

#### `services/master_orchestrator/` — **Undeployed; gates risk_metrics writer**

| File | Role |
|------|------|
| `main.py` | `POST /workflows/market-trio` |
| `consumer.py` | NATS `snapshots.packaged.>` triggers workflow |
| `workflow.py` | Spawn 3 agents → debate → trade ticket |
| `db.py` | Inserts `orders`, publishes `orders.proposed.*` |
| `debate.py` | Multi-agent debate transcript |

---

#### `services/guard_service/` — **Undeployed**

| File | Role |
|------|------|
| `app.py` | HTTP `POST /v1/validate-agent-output`, gRPC :7040 |
| `validator.py` | Constitution validation |
| `creative_classifier.py` | LLM classifier for creative violations |
| `db.py` | Writes `guard_violations`, publishes `agents.violations.escalated.*` |

---

#### `services/risk_service/` — **Staged, inactive (no portfolios)**

| File | Role |
|------|------|
| `app.py` | `POST /v1/validate-order`, `/v1/compute-portfolio-metrics`, gRPC :7060 |
| `validator.py` | Pre-trade risk checks |
| Uses `zinc_native._zinc_risk` (C++ VaR/CVaR) |

**DB:** `portfolios`, `positions`, `risk_metrics` — empty by design today.

---

#### `services/compliance_service/` — **Undeployed**

| File | Role |
|------|------|
| `app.py` | `POST /v1/check-order`, gRPC :7070 |
| `rules/*.py` | RestrictedList, MandateConstraints, WashSale, PDT, AML structuring |

**DB:** `compliance_checks`, reads `portfolios`, `positions`, `orders`.

---

#### `services/oms/` — **Undeployed; live-trading-adjacent**

| File | Role |
|------|------|
| `app.py` | `POST /oms/orders/{id}/approve`, `/oms/reconciliation/resolve` |
| `consumer.py` | NATS: `orders.proposed.>`, `broker.fills.>` |
| `reconciliation.py` | Drift detection → `risk.breaches.reconciliation`, Redis submission pause |
| `state.py` | Order state machine via `zinc_native.oms` |

---

#### `services/broker_adapter_alpaca/` — **Undeployed; live-trading-gated**

| File | Role |
|------|------|
| `app.py` | `GET /v1/positions`, `/v1/orders`, `POST /v1/orders/market` |
| `live_gate.py` | **`assert_live_trading_allowed()`** — requires `accounts.metadata.live_approval=true` |
| `consumer.py` | NATS `orders.approved.>` → Alpaca submit |
| `streamer.py` | Alpaca WS → NATS `broker.fills.{order_id}` |

---

#### `services/backtest_engine/` — **Undeployed**

| File | Role |
|------|------|
| `app.py` | `POST /backtest/run`, status, results |
| `walk_forward.py`, `parquet.py`, `metrics.py` | C++ backtest via zinc_native |
| `universe.py` | Instrument universe for backtests |

---

#### `services/audit_service/` — **Verify API undeployed; writes live via BaseWorker**

| File | Role |
|------|------|
| `app.py` | `GET /audit/verify` |
| `consumer.py` | NATS `audit.events.>` → hash-chain append |
| `chain.py`, `export.py` | SHA-256 chain, WORM checkpoints |

---

#### `services/rnd_agent/` — **Undeployed**

| File | Role |
|------|------|
| `app.py` | `GET /status`, `POST /run/trigger` |
| `runner.py` | Nightly proposal generation |
| `probe.py` | Verifies `tb_rnd_readonly` DB role at startup |
| `email_digest.py` | SMTP pending-proposal alerts |

---

#### Stubs

- `services/api/` — empty placeholder; real external API in sibling **TheEyeBetaDataAPI** repo (`docs/api-gateway.md`)
- `services/worker/` — empty placeholder
- `services/llm_gateway/` — LiteLLM config + `provision_virtual_keys.py`; proxy deployed as `theeyebeta-litellm`

---

### Workers inventory (`workers/`)

All extend `BaseWorker` → writes `worker_runs`, `worker_heartbeats`, `trask_components`.

| Worker file | Class | Schedule (UTC) | Tables touched | Frontend |
|-------------|-------|----------------|----------------|----------|
| `macro_ingestion_worker.py` | MacroIngestionWorker | Mon–Fri 21:20 | `macro_indicators`, `audit_data_gaps`, `audit_alerts` | **None** |
| `macro_regime_worker.py` | MacroRegimeWorker | Chained | `macro_regime_snapshots` | **None** |
| `massive_ingestion_worker.py` | MassiveDailyIngestionWorker | Mon–Fri 21:30 | `prices_daily`, gaps/alerts | **None** |
| `intraday_ingestion_worker.py` | IntradayIngestionWorker | Every 15m market hours | `prices_intraday` | **None** |
| `daily_pipeline_runner.py` | DailyPipelineRunner | Mon–Fri 21:35 | triggers indicators | **None** |
| `indicator_compute_worker.py` | IndicatorComputeWorker | Chained | `ind_technical_daily` | **None** |
| `theeyebeta_indicator_worker.py` | TheeyebetaIndicatorWorker | Chained | validation reads | **None** |
| `sector_aggregation_worker.py` | SectorAggregationWorker | Mon–Fri 22:05 | `sector_daily` | **None** |
| `market_cap_fetch_worker.py` | MarketCapFetchWorker | Daily 21:00 | `market_cap_daily` | **None** |
| `market_cap_threshold_worker.py` | MarketCapThresholdWorker | Chained | `audit_cap_events` | **None** |
| `gap_sentinel_worker.py` | GapSentinelWorker | Mon–Fri 07:30 | gaps, alerts, stuck runs | **None** |
| `supabase_sync_worker.py` | SupabaseSyncV2Worker | Mon–Fri 22:20 | external Supabase | **None** (broken per #5) |

Support: `calendar.py`, `universe_tiers.py`, `fred_client.py`, `indicator_math.py`, `massive_providers.py`, `argos_features.py`, etc.

---

### CLI inventory (`tb/tb/commands/`)

| Command group | File | Key commands | Frontend equivalent |
|---------------|------|--------------|---------------------|
| `status` | `status_cmd.py` | universe, docker, timers, freshness | **Missing** |
| `now` | `now.py` | price, indicators, news, signals, diagnose | **Missing** |
| `trask` | `trask.py` | status, dashboard, events, findings, audit | **Missing** |
| `workers` | `workers.py` | list, run, tail, schedule | **Missing** |
| `pipeline` | `pipeline.py` | daily, status, dry-run, report | **Missing** |
| `universe` | `universe.py` | sync, tiers, list, search, coverage | **Missing** |
| `prices` | `prices.py` | freshness, range, sample, ingest, gaps | **Missing** |
| `indicators` | `indicators.py` | latest, compute, null-report | **Missing** |
| `canonical` | `canonical.py` | status, gaps | **Missing** |
| `intraday` | `intraday.py` | coverage, latest | **Missing** |
| `quant` | `quant.py` | returns, corr, var | **Missing** |
| `backtest` | `backtest.py` | run, status, results | Partial (admin API) |
| `signals` | `signals.py` | latest, scan | **Stub — no backend** |
| `db` | `db.py` | migrate, shell, ping, verify, stats | Partial (SQL page) |
| `secrets` | `secrets.py` | decrypt, edit | **Missing — must stay CLI/sops** |
| `prelive` | `prelive.py` | go/no-go harness | **Missing** |
| `config` | `config.py` | show, validate, env check | **Missing** |

---

### Database schema (`db/migrations/versions/` — 47 tables)

**Core domains:**

| Domain | Tables | Owner |
|--------|--------|-------|
| Instruments | `exchanges`, `instruments`, `market_calendars`, `holidays`, `public_ticker_map` | shared |
| Market data | `prices_daily`, `prices_intraday`, `corporate_actions`, `fundamentals`, `macro_indicators`, `news_*`, `ind_technical_daily`, `sector_daily`, `market_cap_daily` | data workers |
| Agents | `agents`, `agent_runs`, `agent_decisions`, `agent_messages`, `agent_memory` | agent_runtime |
| Trading | `accounts`, `portfolios`, `strategies`, `signals`, `orders`, `executions`, `positions` | oms (empty book) |
| Risk/compliance | `backtest_*`, `risk_metrics`, `compliance_checks`, `guard_violations` | respective services |
| Ops | `worker_runs`, `worker_heartbeats`, `trask_components`, `trask_circuit_breakers`, `audit_data_gaps`, `audit_alerts`, `audit_cap_events`, `trading_calendar` | workers/trask |
| Audit | `audit_log` (+ partitions), `audit_checkpoints`, `system_audit_summary` view | audit_service |
| Costs | `model_runs`, `api_costs` | LLM tracking |
| Snapshots | `data_snapshots`, `data_snapshots_packaged` | packager |

**No `users`, `sessions`, or RBAC tables in this repo's migrations.** `MASTER_ADMIN` is a design requirement, not implemented.

---

### NATS subject map (event bus — invisible in UI today)

| Subject | Publisher | Consumer | Frontend need |
|---------|-----------|----------|---------------|
| `data.snapshots.{market}.{date}` | data_ingestion | snapshot_packager | Pipeline monitor |
| `snapshots.packaged.{market}.{date}` | snapshot_packager | master_orchestrator | Workflow trigger status |
| `agents.decisions.{agent_id}` | agent_runtime | (downstream) | Agent output stream |
| `agents.violations.escalated.{id}` | guard_service | — | Alert panel |
| `orders.proposed.{order_id}` | master_orchestrator | oms | Order blotter |
| `orders.approved.{order_id}` | admin/oms | broker_adapter | Approval audit |
| `broker.fills.{order_id}` | broker_adapter | oms | Fill feed |
| `risk.breaches.reconciliation` | oms reconciliation | — | **Critical alert** |
| `audit.events.>` | all services | audit_service | Audit stream |
| `backtests.requested` | admin proposals | backtest_engine | Job queue |

---

### C++ compute (`cpp/` + `libs/zinc_native/`)

| Module | Computes | Used by | Frontend |
|--------|----------|---------|----------|
| `zinc::risk` | VaR, CVaR, max drawdown, correlation | risk_service, tb quant | **No exposure** |
| `zinc::ta` | RSI, Bollinger, HMM regime, ADX | snapshot_packager, indicators | **No exposure** |
| `zinc::opt` | MVO, Black-Litterman, HRP | research agents | **No exposure** |
| `zinc::bt` | Vectorized backtest | backtest_engine | Results only via admin |
| `zinc::oms` | Order state machine, positions | oms | **No exposure** |

---

### Config / infra / tests (classified, not skipped)

| Category | Paths | Frontend relevance |
|----------|-------|-------------------|
| Docker Compose | `docker-compose.yml` | 10 infra services — status via `tb status`, not admin UI |
| Grafana | `infra/grafana/dashboards/services.json` | Embedded iframe on dashboard only |
| Systemd | `deploy/systemd/theeye-*.timer` (12 timers) | **Zero UI control** |
| CI | `.github/workflows/ci.yml`, `paper-smoke.yml` | Ops visibility only |
| OpenAPI | `docs/api/admin.openapi.json`, `oms.openapi.json` | Contract for terminal API client |
| Tests | `tests/unit/`, `services/*/tests/`, `tests/smoke/`, `tests/e2e/` | Define expected behavior — not user-facing |
| Agent specs | `agents/**/*.agent.md` (58) | Constitution viewer partial |
| Secrets | `secrets/*.enc.yaml.template`, `.sops.yaml` | **Backend-only** — sops CLI |
| Reference data | `db/reference/universe_*.txt` | Universe management via CLI only |

---

## PHASE 2 — Backend Feature Registry

| ID | Feature | Classification | Location | Inputs | Outputs | Failure modes | Required frontend status |
|----|---------|----------------|----------|--------|---------|---------------|--------------------------|
| F01 | EOD price ingestion | Data ingestion | `workers/massive_ingestion_worker.py` | Massive/Finnhub/yfinance API, universe | `prices_daily` | API rate limits, symbol mapping | Last run, rows written, lag vs calendar |
| F02 | Intraday 15m bars | Data ingestion | `workers/intraday_ingestion_worker.py` | Massive API, ≥$500M tier | `prices_intraday` | Delayed feed gaps | Coverage %, latest bar ts |
| F03 | Macro FRED ingest | Data ingestion | `workers/macro_ingestion_worker.py`, `scripts/macro_ingestor/*` | FRED API, 155-series registry | `macro_indicators` | Series discontinuation | Series freshness matrix |
| F04 | Macro regime | Data processing | `workers/macro_regime_worker.py` | macro indicators | `macro_regime_snapshots` | Missing inputs | Regime label + confidence |
| F05 | Technical indicators | Data processing | `workers/indicator_compute_worker.py`, `indicator_math.py` | `prices_daily` | `ind_technical_daily` | Null RSI on thin history | Null-report per symbol |
| F06 | Sector aggregation | Data processing | `workers/sector_aggregation_worker.py` | prices + indicators | `sector_daily` | Sector mapping errors | Sector heatmap data |
| F07 | Market cap tiers | Data processing | `workers/market_cap_*`, `scripts/select_universe_by_cap.py` | Massive reference | `market_cap_daily`, `audit_cap_events` | Threshold crossing missed | Tier counts, crossing events |
| F08 | Gap sentinel | Logging/monitoring | `workers/gap_sentinel_worker.py` | calendar, worker_runs, prices | `audit_data_gaps`, `audit_alerts` | False positives | CRITICAL/WARN alert queue |
| F09 | Snapshot packaging | Data processing | `services/snapshot_packager/` | PG market data | MinIO parquet + `data_snapshots_packaged` | Schema validation fail | Build status, checksum |
| F10 | Packaged snapshot trigger | Task scheduling | NATS consumer in packager | `data.snapshots.*` | `snapshots.packaged.*` | NATS disconnect | Event lag monitor |
| F11 | Agent execution | Agent/automation | `services/agent_runtime/runner.py` | Packaged snapshot, constitution | `agent_runs`, `agent_decisions` | Guard rejection, LLM timeout | Run status, token cost, violations |
| F12 | Market trio workflow | Agent/automation | `services/master_orchestrator/workflow.py` | Packaged snapshot event | `orders` proposed, debate transcript | Agent disagreement, compliance block | Workflow stepper + ticket preview |
| F13 | Guard validation | Risk calculation | `services/guard_service/validator.py` | Agent output JSON | `guard_violations` | LLM classifier false negative | Violation queue (partial UI ✓) |
| F14 | Pre-trade risk | Risk calculation | `services/risk_service/validator.py` | Order + portfolio | Pass/fail + metrics | C++ build missing, empty book | VaR/CVaR dashboard (empty today) |
| F15 | Compliance rules | Legal/compliance | `compliance_service/rules/*` | Order proposal | `compliance_checks` | Rule config drift | Rule hit log — **no UI** |
| F16 | OMS lifecycle | Portfolio/account | `services/oms/` | NATS orders, fills | `orders`, `executions`, `positions` | Reconciliation drift | Blotter + position ledger — **partial** |
| F17 | Broker Alpaca | External integrations | `broker_adapter_alpaca/` | Approved orders | Fills, broker state | Live gate, API outage | Broker connectivity + paper/live mode |
| F18 | Live trading gate | Security-sensitive | `live_gate.py` | `accounts.metadata.live_approval` | Runtime allow/deny | Accidental live enable | **Kill switch UI mandatory** |
| F19 | Order human approval | Admin/system | `admin_service/api/orders.py` | Pending orders | NATS approve | Double-approve race | Blotter ✓ |
| F20 | Proposal R&D loop | Signal generation | `services/rnd_agent/` | Snapshots, backtests | `proposals` | Readonly probe fail | Proposal queue ✓ |
| F21 | Backtest engine | Market analysis | `services/backtest_engine/` | Strategy params, parquet | `backtest_runs/results` | Data missing | Run queue + equity curve |
| F22 | Hash-chain audit | Legal/compliance/audit | `audit_service/chain.py`, BaseWorker | NATS audit events | `audit_log` | Chain break | Verify UI ✓, stream missing |
| F23 | Admin SQL sandbox | Admin/system | `admin_service/api/sql.py` | SQL text | Query results / writes | Destructive SQL | SQL page ✓ (dangerous) |
| F24 | Service restart | Admin/system | `admin_service/api/services.py` | systemctl | Unit restart | sudo failure | **4 units only — weak** |
| F25 | Worker orchestration | Task scheduling | systemd timers + `tb workers` | cron | worker_runs | Stuck runs | Trask dashboard — **CLI only** |
| F26 | Trask circuit breakers | Logging/monitoring | `trask_circuit_breakers` table | worker failures | breaker open/close | Silent pipeline halt | Breaker panel — **CLI only** |
| F27 | LLM gateway | External integrations | LiteLLM :4000, `config/litellm.yaml` | Virtual keys | chat completions | Cost overrun | Model routing + key mgmt |
| F28 | Supabase sync | External integrations | `workers/supabase_sync_worker.py` | packaged snapshots | external DB | **Broken (#5)** | Sync status + shadow/live toggle |
| F29 | News ingest | Sentiment/news | `scripts/run_news_ingest.py` | RSS feeds | `news_articles` | Feed parse errors | Ingest lag, article count |
| F30 | Risk metrics refresh | Risk calculation | `scripts/risk_metrics_refresh.py` | portfolios (empty) | `risk_metrics` | No-op when empty | Writer heartbeat |
| F31 | C++ quant primitives | Market analysis | `cpp/src/risk/*`, `ta/*`, `opt/*` | NumPy arrays | metrics | Build not run | Compute job status |
| F32 | Universe management | Configuration | `tb universe`, `db/reference/universe_*.txt` | cap tiers, files | `instruments.active` | Orphan symbols | Universe editor |
| F33 | Pre-live check | Admin/system | `scripts/prelive_check.py` | 12 read-only probes | pass/fail report | Hidden failures | Go/no-go panel |
| F34 | Secrets (sops) | Security-sensitive | `scripts/decrypt-env.sh`, sops | age keys | decrypted env | Key rotation drift | **CLI only — correct** |
| F35 | External Data API | External integrations | Sibling repo `:7000` | HTTP clients | market queries | Not in this repo | Terminal market data pane |

---

## PHASE 3 — Frontend Exposure Audit (selected critical features)

| Feature | Backend source | Frontend module | UI type | Actions | Priority |
|---------|----------------|-----------------|---------|---------|----------|
| Pending order approval | `admin_service/api/orders.py` | Trading → Orders | Dense blotter + modals | Approve/reject | **Critical** |
| Live trading gate | `broker_adapter_alpaca/live_gate.py` | Admin → System Control | Kill switch + approval workflow | Enable live (DB flag), emergency halt | **Critical** |
| Worker pipeline status | `workers/*`, `trask_components` | Ops → Pipelines | Live table + Gantt | Run/retry/dry-run | **Critical** |
| Gap sentinel alerts | `gap_sentinel_worker.py` | Ops → Alerts | Alert feed | Acknowledge, assign | **Critical** |
| Trask circuit breakers | `trask_circuit_breakers` | Ops → Workers | Status board | Reset breaker (with audit) | **Critical** |
| Audit chain verify | `audit_service`, admin audit | Compliance → Audit | Verify panel + checkpoint table | Verify range, export WORM | **Critical** |
| SQL write sandbox | `admin_service/api/sql.py` | Admin → SQL Console | Editor + confirm modal | SELECT/controlled DML | **High** (dangerous) |
| Agent manual run | `agent_runtime`, admin agents | Agents → Registry | Split pane: list + constitution | Trigger run, view decisions | **High** |
| MO market-trio | `master_orchestrator` | Agents → Workflows | Stepper + debate transcript | Trigger manual, cancel | **High** |
| Compliance rule hits | `compliance_service` | Legal → Compliance | Rule violation table | Override (MASTER_ADMIN + audit) | **High** |
| Risk metrics | `risk_service` | Risk → Portfolio | VaR/CVaR charts | Refresh, stress scenario | **High** (blocked: no book) |
| OMS reconciliation | `oms/reconciliation.py` | Trading → Reconciliation | Drift table | Resolve, pause submissions | **High** |
| Backtest queue | `backtest_engine`, admin | Research → Backtests | Job table + results | Start, cancel, compare | **High** |
| Universe tiers | `universe_tiers.py`, workers | Market Data → Universe | Tier table | Sync, apply cap filter | **High** |
| Service health (all 16) | systemd + docker | Command Center | Status grid | Restart (whitelisted) | **High** |
| LLM costs | admin costs | Finance → Costs | Charts ✓ exist | Budget alerts | **Medium** |
| Intraday coverage | `intraday_ingestion_worker` | Market Data → Intraday | Heatmap | Force backfill | **Medium** |
| News/sentiment | `run_news_ingest.py`, agents | News → Feed | Ticker-filtered stream | Re-ingest | **Medium** |
| Signals | `theeyebeta.signals` table | Signals → Scanner | **Stub CLI only** | Scan, filter | **Medium** (#3 cutover) |
| Supabase sync | `supabase_sync_worker` | Data → External Sync | Status + diff | Shadow/live toggle | **Low** (broken) |
| Secrets management | sops scripts | **Backend-only** | — | Never in browser | N/A |

---

## PHASE 4 — Bloomberg-Terminal Information Architecture

### 1. Full navigation map

```
[⌘K Command Palette — always on top]

┌─ COMMAND CENTER ─────────────────────────────────────────────┐
│ HOME          System pulse, timers, breakers, prelive, NATS   │
│ ALERTS        audit_alerts, gap findings, guard escalations   │
└──────────────────────────────────────────────────────────────┘
┌─ MARKET DATA ────────────────────────────────────────────────┐
│ UNIVERSE      tiers, instruments, coverage, cap events      │
│ PRICES        EOD/intraday freshness, gaps, chart              │
│ INDICATORS    technicals, null report, sector aggregates      │
│ MACRO         FRED series, regime snapshot                    │
│ FUNDAMENTALS  coverage, latest filings                        │
│ NEWS          articles, embeddings status                     │
└──────────────────────────────────────────────────────────────┘
┌─ RESEARCH ───────────────────────────────────────────────────┐
│ SNAPSHOTS     packaged builds, MinIO objects                  │
│ BACKTESTS     queue, results, walk-forward                    │
│ PROPOSALS     R&D queue (exists today)                        │
│ SIGNALS       scanner (post #3 cutover)                       │
└──────────────────────────────────────────────────────────────┘
┌─ TRADING ────────────────────────────────────────────────────┐
│ ORDERS        pending blotter (exists today)                  │
│ POSITIONS     ledger, P&L (needs OMS deploy)                  │
│ RECONCILIATION broker vs internal drift                         │
│ BROKER        Alpaca status, paper/live gate                    │
└──────────────────────────────────────────────────────────────┘
┌─ RISK ───────────────────────────────────────────────────────┐
│ PORTFOLIO     VaR/CVaR, correlation, drawdown                 │
│ LIMITS        mandate constraints, pre-trade checks           │
│ STRESS        scenario shocks (C++ opt/risk)                  │
└──────────────────────────────────────────────────────────────┘
┌─ AGENTS ─────────────────────────────────────────────────────┐
│ REGISTRY      58 agents, runs, constitution (partial today)   │
│ WORKFLOWS     market-trio, debate transcripts                 │
│ COSTS         LLM spend (exists today)                        │
└──────────────────────────────────────────────────────────────┘
┌─ COMPLIANCE & AUDIT ─────────────────────────────────────────┐
│ AUDIT LOG     hash chain (exists today)                       │
│ VIOLATIONS    guard (exists today)                            │
│ COMPLIANCE    rule checks, wash sale, PDT, AML                │
│ LEGAL         contract/regulatory agents (read-only runs)     │
└──────────────────────────────────────────────────────────────┘
┌─ OPS ────────────────────────────────────────────────────────┐
│ PIPELINES     worker runs, schedules, Trask dashboard       │
│ WORKERS       run/tail/retry                                  │
│ SERVICES      systemd/docker health (partial JSON API)      │
│ OBSERVABILITY Grafana/Loki/Tempo deep links                   │
│ SQL CONSOLE   exists today — restrict to MASTER_ADMIN       │
└──────────────────────────────────────────────────────────────┘
┌─ ADMIN ──────────────────────────────────────────────────────┐
│ USERS         RBAC — **does not exist yet**                   │
│ CONFIG        env validation, litellm routing                 │
│ SYSTEM        live gate, kill switches, emergency stop        │
│ CLI           embedded terminal mirroring `tb`                  │
└──────────────────────────────────────────────────────────────┘
```

### 2. Command palette commands (mirror `tb` CLI)

| Command | Maps to | Shortcut |
|---------|---------|----------|
| `:status` | `tb status` | `Ctrl+Shift+S` |
| `:now AAPL` | `tb now price AAPL` | `Ctrl+N` |
| `:workers list` | `tb workers list` | `Ctrl+W` |
| `:workers run massive-ingest` | manual worker | — |
| `:trask dashboard` | live ops board | `Ctrl+T` |
| `:pipeline status` | daily pipeline | — |
| `:canonical gaps` | data gaps | — |
| `:prelive` | go/no-go | `Ctrl+Shift+P` |
| `:audit verify` | chain verify | — |
| `:orders pending` | navigate blotter | `Ctrl+O` |
| `:agent run macro-lead` | trigger agent | — |
| `:backtest run` | start backtest | — |
| `:sql` | SQL console | `` Ctrl+` `` |
| `:kill live-trading` | emergency halt | `Ctrl+Shift+K` (confirm x2) |

### 3. Keyboard shortcuts (terminal conventions)

- `F1`–`F12`: jump to primary modules (Home, Market, Trade, Risk, Agents, Ops)
- `/`: focus command line
- `Esc`: close modal / cancel
- `Ctrl+R`: refresh active panel
- `Ctrl+F`: filter active table
- `j/k`: vim row navigation in tables
- `Enter`: drill-down on selected row
- `a`: approve (orders/proposals) with confirm
- `x`: reject with reason modal

### 4. Tables needed

Worker registry, run history, circuit breakers, orders blotter, audit_log, guard_violations, proposals, backtest_runs, audit_alerts, audit_data_gaps, instruments/universe, compliance_checks, risk_metrics, positions, executions, macro series registry, api_costs/model_runs.

### 5. Charts needed

Price OHLCV, indicator overlays, sector heatmap, daily cost stacked bar (exists), VaR time series, backtest equity curve, intraday coverage heatmap, pipeline timeline Gantt.

### 6. Logs needed

Per-worker journal tail, NATS subject monitor, service structlog stream via Loki.

### 7. Admin controls needed

All systemd timers, all 16 services, live trading gate, circuit breaker reset, reconciliation resolve, LLM virtual keys, universe apply.

### 8. Agent controls needed

Run/stop (if running), view constitution, decision stream, guard escalation ack.

### 9. Risk/compliance controls needed

Pre-trade simulation, rule override with mandatory audit, reconciliation pause toggle.

### 10. CLI-equivalent actions

Every `tb` command group should be reachable via command palette or embedded CLI panel.

### 11. Module grouping

See navigation map above — 8 top-level zones, 30+ sub-modules.

### 12. Dual workflow support

- **Visual:** pages, tables, panels, modals
- **Command-driven:** CLI/command console with `:command` syntax

---

## PHASE 5 — Page Specifications (dense operational)

### P01 — Command Center / Home

| Field | Spec |
|-------|------|
| Purpose | Single-pane operational pulse |
| User | MASTER_ADMIN, Operator, Analyst (read-only subset) |
| Backend | `tb status`, `trask_components`, `worker_runs`, `audit_alerts`, systemd timers, `GET /admin/health`, Grafana |
| Data | Open breakers, last pipeline run, price freshness age, pending orders count, LLM MTD cost, prelive last result |
| Controls | Run prelive, verify audit, jump to failed worker, trigger daily backtest |
| Layout | 4×4 stat grid top; left: alert feed; center: pipeline timeline; right: timer schedule; bottom: command line |
| APIs needed | `GET /admin/ops/pulse`, `GET /admin/workers/status`, `GET /admin/trask/dashboard` — **all missing** |
| Permissions | Read: Analyst+; Actions: Operator+; Kill switches: MASTER_ADMIN |

### P02 — Pipeline / Workers (Trask)

| Field | Spec |
|-------|------|
| Purpose | Control data ingestion and processing fleet |
| Backend | `workers/*`, `worker_runs`, `trask_components`, `trask_circuit_breakers`, systemd |
| Data | Component state, last heartbeat, records written/expected, failure traceback, next timer fire |
| Controls | Run now (dry-run/real), tail logs, retry failed, open/reset breaker (confirmed), enable/disable timer |
| Tables | Worker registry, run history, circuit breakers |
| Charts | Pipeline waterfall (21:00→22:20 UTC sequence) |
| APIs needed | `POST /admin/workers/{name}/run`, `GET /admin/workers/runs`, `POST /admin/trask/breakers/{id}/reset` |
| MASTER_ADMIN | Full run/stop/retry/schedule override — **requires new worker control API + sudo policy** |

### P03 — Market Data / Universe

| Field | Spec |
|-------|------|
| Purpose | Canonical data health and universe management |
| Backend | `prices_daily`, `prices_intraday`, `instruments`, `public_ticker_map`, `market_cap_daily`, sibling Data API :7000 |
| Data | Tier counts (EOD vs intraday ≥$500M), symbol search, coverage %, cap crossing events |
| Controls | Universe sync, apply tier, instrument add/remove (currently stub in CLI) |
| APIs needed | Proxy to Data API + `POST /admin/universe/sync`, `GET /admin/universe/coverage` |

### P04 — Prices / Indicators / Macro

| Field | Spec |
|-------|------|
| Purpose | Operator analytics without leaving terminal |
| Backend | `tb prices`, `tb indicators`, `tb plot`, macro workers, `macro_regime_snapshots` |
| Data | Freshness matrix, gap list, latest indicators, regime classification |
| Controls | Trigger backfill (`scripts/backfill_prices.py` wrapper), recompute indicators |
| Charts | Multi-pane price + RSI/MACD (TradingView-style density) |

### P05 — Orders (exists — upgrade)

| Field | Spec |
|-------|------|
| Purpose | Human-in-the-loop trade approval |
| Backend | `admin_service/api/orders.py`, OMS (when deployed) |
| Current | htmx blotter at `/admin/orders` |
| Gaps | No positions view, no fill feed, no broker status, no compliance pre-check display before approve |
| Required | WebSocket `orders.proposed.*`, `broker.fills.*`; show risk + compliance verdict inline |

### P06 — Risk Dashboard

| Field | Spec |
|-------|------|
| Purpose | Portfolio risk visibility |
| Backend | `risk_service`, `risk_metrics`, C++ zinc::risk |
| Status | **Empty — no portfolios**. UI must show "no book" explicitly, not fake zeros |
| Controls | Compute metrics refresh, stress scenarios |
| APIs | `GET /admin/risk/metrics`, `POST /admin/risk/compute` — proxy risk_service |

### P07 — Agents (exists — expand)

| Field | Spec |
|-------|------|
| Purpose | Agent fleet operations |
| Backend | `agents` table, `agent_runtime`, 58 constitution files |
| Current | List, runs, constitution, manual run |
| Gaps | No streaming decisions, no department filter, no veto-agent highlighting, no NATS monitor |
| Controls | Bulk run, disable agent, hot-reload constitution (with audit) |

### P08 — Workflows (master orchestrator)

| Field | Spec |
|-------|------|
| Purpose | Slow/fast loop coordination |
| Backend | `master_orchestrator/workflow.py`, NATS packaged snapshots |
| Data | Workflow instances, debate transcripts, proposed tickets |
| Controls | Manual trigger `POST /workflows/market-trio`, cancel in-flight (needs cancel API) |
| Status | Service **undeployed** — page shows deployment blocker |

### P09 — Audit & Compliance

| Field | Spec |
|-------|------|
| Purpose | Regulatory-grade traceability |
| Backend | `audit_log`, `audit_service`, `compliance_checks`, `guard_violations` |
| Current | Audit log + verify + violations |
| Gaps | No compliance_checks UI, no checkpoint browser, no WORM export trigger, no immutable table policy banner |
| Controls | Verify chain, export checkpoint, resolve violations ✓ |

### P10 — Proposals (exists)

| Field | Spec |
|-------|------|
| Purpose | R&D proposal review |
| Backend | `rnd_agent`, `proposals`, backtest validation |
| Current | Tabbed list, approve/reject, backtest poll |
| Gaps | No evidence drill-down to snapshots, no impact estimation charts |

### P11 — Backtests

| Field | Spec |
|-------|------|
| Purpose | Research job management |
| Backend | `backtest_engine`, admin backtest API |
| Current | JSON API + dashboard button only |
| Required | Full page: queue, equity curve, metrics table, compare runs |

### P12 — Services / System Control

| Field | Spec |
|-------|------|
| Purpose | Infrastructure operations |
| Backend | `admin_service/api/services.py` (4 units!), docker compose, all systemd |
| Gaps | Docs say Docker; code uses systemd; only admin-service + llm-gateway restartable |
| MASTER_ADMIN needs | All 16 services + 12 timers + NATS/Redis/Postgres health |

### P13 — SQL Console (exists — restrict)

| Field | Spec |
|-------|------|
| Purpose | Ad hoc data investigation |
| Backend | `admin_service/api/sql.py` |
| Risk | Write path bypasses normal UX; blocks audit/proposals but not orders |
| Required | MASTER_ADMIN only for execute; read-only role for Analyst; query history audit |

### P14 — CLI Terminal (embedded)

| Field | Spec |
|-------|------|
| Purpose | `tb` parity in browser |
| Backend | WebSocket shell to restricted `tb` subprocess OR REST command proxy |
| Security | Command whitelist, no `secrets`, no raw `psql`, audit every command |

### P15 — Users & Permissions (**greenfield**)

| Field | Spec |
|-------|------|
| Purpose | RBAC for MASTER_ADMIN, Operator, Analyst, Compliance, Read-only |
| Backend | **No tables exist** — must add `users`, `roles`, `permissions`, JWT claims |
| Controls | Assign roles, lock accounts, session revoke |

### P16 — Login (**missing**)

| Field | Spec |
|-------|------|
| Purpose | Authentication entry |
| Current | API exists; nav redirects to `/admin/login` — **route does not exist** |
| Required | Login page, MFA (future), refresh flow |

---

## PHASE 6 — Master Control Matrix

Legend: ✓=yes, ✗=no, ~=partial, BO=backend-only with reason

| Backend feature | Source | Frontend location | View | Control | Edit | Schedule | Kill switch | Confirm | Role | Audit | API exists | Missing work | Priority |
|-----------------|--------|-------------------|------|---------|------|----------|-------------|---------|------|-------|------------|--------------|----------|
| EOD ingest | `massive_ingestion_worker` | Ops→Pipelines | ✗ | ✗ | ✗ | ~CLI | ✗ | ✗ | Op | ✓ runs | ✗ | Worker API | **Critical** |
| Intraday ingest | `intraday_ingestion_worker` | Market→Intraday | ✗ | ✗ | ✗ | ~timer | ✗ | ✗ | Op | ✓ | ✗ | Worker API | High |
| Macro pipeline | `macro_pipeline` | Market→Macro | ✗ | ✗ | ✗ | ~timer | ✗ | ✗ | Op | ✓ | ✗ | Worker API | High |
| Indicators | `indicator_compute_worker` | Market→Indicators | ✗ | ✗ | ✗ | ~timer | ✗ | ✗ | Op | ✓ | ✗ | Worker API | High |
| Gap sentinel | `gap_sentinel_worker` | Ops→Alerts | ✗ | ✗ | ✗ | auto | ✗ | ✗ | All | ✓ alerts | ✗ | Alerts API | **Critical** |
| Trask breakers | `trask_circuit_breakers` | Ops→Workers | ✗ | ✗ | ✗ | auto | ✓ needed | ✓ | MASTER | ✓ | ✗ | Breaker API | **Critical** |
| Snapshot build | `snapshot_packager` | Research→Snapshots | ✗ | ✗ | ✗ | event | ✗ | ✗ | Op | ~ | ~HTTP | Deploy + admin proxy | High |
| Agent run | `agent_runtime` | Agents→Registry | ~ | ~ | ✗ | manual | ✗ | ✓ | Op | ✓ | ✓ admin | Deploy service | High |
| Market trio | `master_orchestrator` | Agents→Workflows | ✗ | ✗ | ✗ | event | ✓ | ✓ | MASTER | ✓ | ~HTTP | Deploy + UI | High |
| Guard validate | `guard_service` | Compliance | ~violations | ✗ | ✗ | auto | ✗ | ✗ | Compliance | ✓ | ✗ gRPC | Deploy + proxy | High |
| Risk validate | `risk_service` | Risk | ✗ | ✗ | ✗ | 5m timer | ✗ | ✗ | Risk | ✓ | ✗ gRPC | Deploy + book | High |
| Compliance check | `compliance_service` | Legal→Compliance | ✗ | ✗ | ✗ | per order | ✗ | override✓ | Compliance | ✓ | ✗ | Compliance UI | High |
| OMS approve | `oms/app.py` | Trading→Orders | ~admin | ~ | ✗ | event | ✓ recon pause | ✓ | Op | ✓ | ~ | Deploy OMS | **Critical** |
| Broker submit | `broker_adapter_alpaca` | Trading→Broker | ✗ | ✗ | ✗ | event | **✓ live gate** | ✓✓ | MASTER | ✓ | ~HTTP | Live gate UI | **Critical** |
| Live trading gate | `live_gate.py` | Admin→System | ✗ | ✗ | ✓ DB | — | **✓** | ✓✓ | MASTER | ✓ | ✗ | `POST /admin/trading/live-approval` | **Critical** |
| Order approve UI | `admin/orders` | Trading→Orders | ✓ | ✓ | ✗ | — | ✗ | ✓ | Op | ✓ | ✓ | Add compliance preview | **Critical** |
| Reconciliation | `oms/reconciliation.py` | Trading→Recon | ✗ | ✗ | ✗ | loop | ✓ pause | ✓ | MASTER | ✓ | ~OMS | Recon UI | **Critical** |
| Audit chain | `audit_service` | Compliance→Audit | ✓ | ✓ verify | ✗ | nightly | ✗ | ✓ | Compliance | ✓ | ✓ | Checkpoint page | **Critical** |
| Audit log browse | `admin/audit` | Compliance→Audit | ✓ | ✗ | ✗ | — | ✗ | ✗ | All | — | ✓ | Live stream | High |
| SQL SELECT | `admin/sql` | Ops→SQL | ✓ | ✓ | ✗ | — | ✗ | ✗ | Analyst+ | ✓ | ✓ | RBAC split | High |
| SQL WRITE | `admin/sql` | Ops→SQL | ✓ | ✓ | ✓ | — | ✗ | ✓✓ | MASTER only | ✓ | ✓ | Restrict role | High |
| Proposals | `admin/proposals` | Research→Proposals | ✓ | ✓ | ✗ | nightly | ✗ | ✓ | Op | ✓ | ✓ | — | High |
| Backtest | `backtest_engine` | Research→Backtests | ~ | ~ | ✗ | manual | ✗ | ✓ | Research | ✓ | ✓ | Results page | High |
| Guard violations | `admin/violations` | Compliance | ✓ | ✓ resolve | ✗ | — | ✗ | ✓ | Compliance | ✓ | ✓ | — | High |
| LLM costs | `admin/costs` | Finance→Costs | ✓ | ✗ | ✗ | — | ✗ | ✗ | Finance | — | ✓ | Budget alerts | Medium |
| Service restart | `admin/services` | Admin→System | ~JSON | ~2 svcs | ✗ | — | ✗ | ✓ | MASTER | ✓ | ✓ | Expand whitelist | High |
| Worker manual run | `tb workers run` | Ops→CLI | ✗ | CLI | ✗ | manual | ✗ | ✓ | Op | ✓ | ✗ | Worker API | **Critical** |
| Universe mgmt | `tb universe` | Market→Universe | ✗ | CLI | ✓ files | daily | ✗ | ✓ | Op | ✓ | ✗ | Universe API | High |
| News ingest | `run_news_ingest.py` | News→Feed | ✗ | ✗ | ✗ | 2h timer | ✗ | ✗ | Op | ~ | ✗ | News API | Medium |
| Supabase sync | `supabase_sync_worker` | Data→Sync | ✗ | ✗ | ✗ | timer | ✗ | ✓ | MASTER | ✓ | ✗ | Fix #5 + UI | Low |
| Secrets/sops | `scripts/decrypt-env.sh` | BO | ✗ | ✗ | ✗ | — | — | — | — | — | BO | Never browser | N/A |
| C++ risk compute | `cpp/src/risk` | Risk | ✗ | ✗ | ✗ | on demand | ✗ | ✗ | Risk | ✓ | indirect | Metrics API | Medium |
| NATS bus | infra | Ops→Events | ✗ | ✗ | ✗ | — | ✗ | ✗ | MASTER | ✓ | ✗ | Event monitor WS | High |
| Login/auth | `admin/auth.py` | — | ✗ | ✗ | ✗ | — | ✗ | — | All | ✓ | ✓ | **Login page** | **Critical** |
| RBAC/MASTER_ADMIN | — | Admin→Users | ✗ | ✗ | ✗ | — | ✗ | — | — | ✓ | ✗ | Full auth system | **Critical** |
| External Data API | sibling repo | Market Data | ✗ | ✗ | ✗ | — | ✗ | ✗ | Analyst | — | external | Integrate :7000 | High |
| Prelive check | `prelive_check.py` | Command Center | ✗ | CLI | ✗ | manual | ✗ | ✗ | Op | ✓ | ✗ | Prelive API | **Critical** |
| Signals scanner | `signals` table | Signals | ✗ | stub CLI | ✗ | — | ✗ | ✗ | Research | — | ✗ | #3 cutover | Medium |

---

## PHASE 7 — Brutal Gaps

### Backend features with zero frontend exposure

- **Entire worker fleet** (12 workers) — only `tb workers` and systemd
- **Trask dashboard** — rich CLI, no web panel
- **All market data queries** (`tb now`, `prices`, `indicators`, `canonical`, `intraday`, `quant`)
- **Master orchestrator workflow** — code exists, service undeployed, no UI
- **Compliance rule engine** — 5 rules, zero visibility
- **OMS reconciliation + submission pause** — dangerous invisible state
- **Live trading gate** — DB flag with no admin control path
- **Broker adapter** — positions/orders endpoints exist, no UI
- **Risk metrics** — writer timer runs into empty table; no explanation in UI
- **NATS event bus** — no monitor
- **Login page** — auth API without UI (broken operator experience)
- **12 systemd timers** — no schedule visibility in admin (docs claim `/market` page — **does not exist**)

### Dangerous without audit logs

- **Worker manual runs via CLI** — audit in `worker_runs` but CLI not attributed to user
- **Live trading enable** — no UI, no audit trail for who set `live_approval`
- **systemctl restart** — only 2 services whitelisted; expanding without audit pattern is risky
- **SQL execute** — audited ✓ but available to single operator with no role split

### Dangerous without RBAC

- **Everything in admin_service** — one bcrypt password protects orders, SQL writes, proposals, service restarts
- **SQL console** — equivalent to raw DB access for trading data
- **Proposal approve** — can trigger backtests and NATS events
- **MASTER_ADMIN requirement is fiction today** — must be built

### Weak architecture (said plainly)

- **Docs lie:** `docs/admin-service.md` lists `/market` page and Docker service restart; code has neither
- **Services_STATUS.md:** 12/14 application services undeployed — frontend cannot "control the ecosystem" until deploy story is fixed
- **Dual API:** sibling Data API repo not integrated — terminal market data will be split-brain
- **Signals:** 8.9M rows in DB per db-engineer rules, but `tb signals` is stub — product lie
- **Supabase sync:** known broken (#5), shadow mode hides failures
- **No users table:** architecture.md mentions users migration that doesn't match actual Alembic history
- **Agent registry vs runtime:** 58 markdown agents, unknown how many in `theeyebeta.agents` table
- **Public schema bridge:** cross-schema complexity invisible to operators

### Missing endpoints (minimum for MASTER_ADMIN control)

```
POST   /admin/auth/login                    ✓ (page missing)
GET    /admin/users                         ✗
POST   /admin/users/{id}/roles              ✗
GET    /admin/ops/pulse                     ✗
GET    /admin/workers                       ✗
POST   /admin/workers/{name}/run            ✗
GET    /admin/workers/runs                  ✗
GET    /admin/trask/dashboard               ✗
POST   /admin/trask/breakers/{id}/reset     ✗
GET    /admin/pipeline/status               ✗
GET    /admin/market/freshness              ✗
GET    /admin/universe                      ✗
POST   /admin/universe/sync                 ✗
GET    /admin/alerts                        ✗
POST   /admin/alerts/{id}/ack               ✗
GET    /admin/risk/metrics                  ✗
POST   /admin/risk/compute                  ✗
GET    /admin/compliance/checks             ✗
GET    /admin/oms/reconciliation            ✗
POST   /admin/oms/reconciliation/resolve    ✗ (exists on OMS, not admin)
GET    /admin/broker/status                 ✗
GET    /admin/broker/positions              ✗
POST   /admin/trading/live-approval         ✗
POST   /admin/trading/emergency-halt        ✗
GET    /admin/nats/subjects                 ✗
WS     /admin/events/stream                 ✗
GET    /admin/timers                        ✗
POST   /admin/timers/{name}/trigger         ✗
POST   /admin/cli/exec                      ✗ (restricted)
GET    /admin/prelive                       ✗
```

### Features that should not be directly controllable

- **Secrets/sops decryption** — must remain CLI-only with age key on host
- **Raw `audit_log` DELETE/UPDATE** — correctly blocked in SQL sandbox; must never be exposed
- **Live trading enable without dual confirm** — controllable only by MASTER_ADMIN with audit
- **Unrestricted SQL write** — MASTER_ADMIN only, never Analyst

### Missing tests, logs, documentation

- **Tests:** No frontend E2E for worker control (doesn't exist); admin smoke tests cover 8 pages only
- **Logs:** Worker failures notify via `theeye_notify_failure.sh` but no UI surfacing
- **Documentation:** `docs/admin-service.md` stale vs `api/services.py` implementation

---

## PHASE 8 — Implementation Backlog

### Critical — required to safely operate

| Task | Why | Backend files | Frontend page/module | API requirement | Acceptance criteria |
|------|-----|---------------|----------------------|-----------------|---------------------|
| Login page + session UX | Auth API unusable | `admin_service/auth.py`, `templates/` | `/admin/login` | exists | Operator can log in, refresh, logout |
| RBAC + MASTER_ADMIN | Single password is unacceptable | new migrations, `auth.py` | Admin→Users | new | JWT carries role; SQL write = MASTER_ADMIN only |
| Command Center pulse | No system visibility | workers, trask, timers | Home | `/admin/ops/pulse` | Shows breakers, last runs, freshness, alerts |
| Worker control API | Data platform is blind | `workers/*`, `base_worker.py` | Ops→Pipelines | `/admin/workers/*` | MASTER_ADMIN can run/retry/dry-run with audit actor |
| Trask/breaker panel | Silent pipeline death | `tb/tb/lib/queries/trask.py` | Ops→Workers | `/admin/trask/*` | Open breakers visible; reset requires confirm + audit |
| Prelive dashboard | Go/no-go hidden in CLI | `scripts/prelive_check.py` | Home | `/admin/prelive` | 12 checks with pass/fail drill-down |
| Live trading gate UI | Accidental live trading | `live_gate.py`, `accounts` | Admin→System | `/admin/trading/*` | Cannot enable live without MASTER_ADMIN + dual confirm + audit |
| Gap/alert feed | Data quality invisible | `audit_alerts`, gap_sentinel | Ops→Alerts | `/admin/alerts` | CRITICAL alerts push to command center |
| Expand service control | 2 restartable units is a joke | `api/services.py`, systemd | Admin→System | extend | All deployed units status; whitelist restart with audit |
| OMS deploy + recon UI | Trading loop incomplete | `services/oms/` | Trading→Recon | proxy OMS | Drift visible; resolve with audit; submission pause indicator |

### High — serious usability

| Task | Why | Backend files involved | Frontend page/module | API requirement | Acceptance criteria |
|------|-----|------------------------|----------------------|-----------------|---------------------|
| Market data terminal pane | Core operator workflow | Data API :7000, `tb now` queries | Market Data | proxy | Symbol lookup, freshness, chart from one pane |
| Universe manager | 500-instrument ops | `universe.py`, `db/reference/universe_*.txt` | Universe | new | Tier sync, coverage report, cap events |
| Backtest results page | JSON endpoint useless alone | `backtest_engine` | Research→Backtests | extend admin | Equity curve, metrics, compare runs |
| Compliance check log | Regulatory gap | `compliance_service` | Legal | proxy | Rule hits per order with drill-down |
| NATS event monitor | Debug workflows | all NATS publishers | Ops→Events | WebSocket | Subject lag, last message ts |
| Agent decision stream | Manual run black box | `agent_runtime/runner.py` | Agents | WS | Live decisions during run |
| Intraday coverage heatmap | Tier-2 data ops | intraday worker | Market→Intraday | new | Coverage % by symbol and session |
| Deploy agent_runtime + MO | Fast loop dead | `SERVICES_STATUS.md` blockers | Agents/Workflows | health checks | Services running, UI shows green |
| Fix admin/docs drift | Operator mistrust | docs + services.py | — | align systemd | Docs match code |
| Embedded CLI (restricted) | `tb` parity | `tb/tb/cli.py` | CLI panel | `/admin/cli/exec` | Whitelisted commands, full audit |

### Medium — workflow improvement

| Task | Why | Backend files involved | Frontend page/module | API requirement | Acceptance criteria |
|------|-----|------------------------|----------------------|-----------------|---------------------|
| Signals scanner UI | #3 cutover | `signals` hypertable | Signals | new | Filter, scan, export |
| Macro series registry browser | 155 FRED series | `macro_series_registry.py` | Macro | new | Freshness per series |
| News feed | Sentiment agents need context | `news_articles` | News | new | Ticker filter, ingest status |
| Risk stress scenarios | C++ opt/risk unused | `cpp/src/risk`, `opt` | Risk | compute API | Scenario results table |
| LLM routing admin | Model costs/control | `config/litellm.yaml` | Admin→Config | read-only first | Model list, key status |
| Checkpoint/WORM export UI | Compliance | `audit_service/export.py` | Audit | proxy | Trigger export, download link |
| Timer schedule editor | Ops convenience | systemd units | Admin→System | read then write | View all 12 timers, manual trigger |

### Low — nice-to-have

| Task | Why | Backend files involved | Frontend page/module | API requirement | Acceptance criteria |
|------|-----|------------------------|----------------------|-----------------|---------------------|
| Supabase sync panel | Blocked on #5 product decision | `supabase_sync_worker` | Data→Sync | fix worker first | Shadow/live toggle works |
| Terminal chart performance | Chart.js limits at scale | — | Market Data | — | Canvas/WebGL charts for OHLCV |
| Agent department org chart | 58 agents navigation | `agents/` | Agents | — | Department tree view |
| Benchmark regression viewer | C++ perf tracking | `scripts/compare_benchmarks.py` | Ops | — | Bench diff table |

---

## PHASE 9 — Final Deliverables

### 1. Repository map

869 files across `services/` (16), `workers/` (23), `tb/` (CLI), `db/migrations/` (26), `cpp/` (5 modules), `libs/` (4), `agents/` (58), `infra/`, `deploy/systemd/` (12 timers), `scripts/` (30+). Stubs: `services/api`, `services/worker`.

### 2. Backend feature registry

35 classified features (F01–F35) in Phase 2. Production today = **data workers + admin_service + LiteLLM + external Data API**. Trading/agent stack = **scaffold**.

### 3. Frontend module map

16 top-level modules in Phase 4 nav. **8 partially implemented** in admin_service (Dashboard, Orders, Audit, Agents, Violations, Costs, SQL, Proposals). **8+ major modules missing** (Market Data, Pipelines, Risk, Trading beyond orders, Compliance rules, System Control, CLI, Users).

### 4. Page-by-page specification

16 pages specified (P01–P16) in Phase 5.

### 5. Master control matrix

40-row matrix in Phase 6; every meaningful backend feature mapped.

### 6. Missing API list

22+ endpoints in Phase 7; WebSocket event stream required.

### 7. Security/risk/audit concerns

- No RBAC; MASTER_ADMIN does not exist in code
- No login page
- Live trading gate with no UI control
- SQL write access for single operator
- Most services unauthenticated on loopback (OK if bound 127.0.0.1; catastrophic if exposed)
- Reconciliation pause invisible
- CLI worker runs not attributed to human operator in audit_log
- `audit_log` itself empty per SERVICES_STATUS notes — chain verify is verifying nothing

### 8. Bloomberg-terminal UX recommendations

- **Dark, monospace-dense, no whitespace waste** — current htmx admin is closer to SaaS dashboard than terminal; rebuild as React/Vue terminal shell or enhance with fixed panels + command line
- **Always-visible command bar** — every `tb` command reachable via `:`
- **Keyboard-first** — j/k navigation, single-key approve/reject with confirm overlay
- **Multi-panel layouts** — save layouts per role (Operator vs Analyst vs Compliance)
- **Live streams** — WebSocket for NATS, fills, agent decisions, alerts (not 30s htmx poll)
- **Status chroma** — green/amber/red for pipeline, breakers, freshness (Bloomberg-style field colors)
- **No marketing copy** — replace "Dashboard" stat cards with operational metrics only
- **Consequence preview** — before approve order/proposal/live-trading, show downstream effects
- **Audit drawer** — every action opens timestamped audit trail side panel

### 9. Implementation backlog

Critical (10), High (10), Medium (7), Low (4) — Phase 8.

### 10. Top 20 frontend features to build first

1. **Login page** — unblocks everything (`auth.py`)
2. **RBAC + MASTER_ADMIN role** — greenfield auth schema
3. **Command Center pulse** — workers + trask + timers + alerts
4. **Worker run/retry/audit panel** — `workers/*`, `worker_runs`
5. **Trask circuit breaker dashboard** — `tb trask dashboard` parity
6. **Gap/alert feed** — `audit_alerts`, gap_sentinel
7. **Prelive go/no-go panel** — `prelive_check.py`
8. **Live trading gate + emergency halt** — `live_gate.py`
9. **Market data freshness matrix** — prices, indicators, canonical
10. **Universe tier manager** — EOD/intraday tiers, cap events
11. **Pipeline timeline (21:00–22:20 UTC)** — all timers visualized
12. **Service health grid (all units)** — extend `api/services.py`
13. **NATS event monitor** — subject lag, last message
14. **Order blotter upgrade** — compliance/risk preview before approve
15. **Backtest results page** — equity curve, metrics
16. **Compliance check log** — when OMS deploys
17. **OMS reconciliation panel** — drift + resolve
18. **Embedded restricted CLI** — `tb` command proxy
19. **Agent decision live stream** — post agent_runtime deploy
20. **Users/permissions admin** — role assignment, session revoke

---

## MASTER_ADMIN Control Authority — Honest Assessment

**Today MASTER_ADMIN cannot exist.** There is one `ADMIN_USERNAME` with full power and no override audit distinction.

| Capability | Current state | Work required |
|------------|---------------|---------------|
| View all workers/services | Partial (4 systemd units, CLI only for workers) | `/admin/ops/*` aggregation API |
| Start/stop/pause workers | CLI/systemd only; `tb trask worker stop` redirects to systemd | `POST /admin/workers/{name}/run`, timer enable/disable, sudo policy |
| Retry failed jobs | `tb workers run --force` | Worker API + audit actor |
| Edit configuration | Env files, sops — no UI | Config API (read); writes via sops CLI only |
| Override restrictions | N/A — no restrictions exist | RBAC + override flag on JWT + mandatory audit |
| Trigger agents/workflows | Partial (agent run via admin) | Deploy services + workflow cancel |
| Schedule jobs | systemd timers invisible | Timer CRUD API (read first, write guarded) |
| Disable features | No kill switches in UI | Live gate, recon pause, breaker reset APIs |
| Inspect logs | `tb workers tail`, journalctl | Log proxy to Loki/journal |
| Inspect I/O | SQL console only | Per-job input/output artifact viewer |
| Failure history | `worker_runs` in DB, CLI `trask audit` | Worker runs UI |
| Audit trail | `audit_log` browse ✓ | User-attributed actions, live stream |
| Assign permissions | **Impossible** | Full IAM schema |
| Lock from non-admin | **Impossible** | RBAC enforcement on every route |
| Emergency kill switch | **Impossible** | `POST /admin/trading/emergency-halt`, NATS pause, Redis submission gate UI |

Every MASTER_ADMIN override must write to `audit_log` with `{override: true, reason, consequences_acknowledged}` — **pattern not implemented**.

---

## Bottom Line

This backend is a serious fintech research platform with a **production-grade data pipeline** and a **prototype admin shell**. The Bloomberg-terminal frontend described in this document requires ~80% net-new UI, a **complete auth/RBAC layer**, **worker control APIs**, and **deployment of 12 dormant services** before MASTER_ADMIN can honestly claim total command authority. The `tb` CLI is the real terminal today — the frontend's first job is to absorb it, not decorate eight htmx pages.

---

## Appendix A — Nightly Pipeline Order (UTC, weekdays)

```
07:30 gap-sentinel
21:00 market-cap (+ universe apply)
21:20 macro (FRED regime pipeline)
21:30 massive-ingest ∥ macro-refresh (FRED incremental + gold + MOVE)
21:35 daily-pipeline + indicator validation
22:05 sector aggregation
22:20 supabase sync (shadow)
```

## Appendix B — Systemd Timers

| Timer | Schedule | Service | Process |
|-------|----------|---------|---------|
| `theeye-backup.timer` | Daily 02:00 | `theeye-backup.service` | `scripts/backup_db.sh` |
| `theeye-gap-sentinel.timer` | Mon–Fri 07:30 | `theeye-gap-sentinel.service` | `workers.gap_sentinel_worker` |
| `theeye-news-ingest.timer` | Every 2h at :17 | `theeye-news-ingest.service` | `scripts/run_news_ingest.py` |
| `theeye-risk-metrics-refresh.timer` | Every 5 min | `theeye-risk-metrics-refresh.service` | `scripts/risk_metrics_refresh.py` |
| `theeye-market-cap.timer` | Daily 21:00 | `theeye-market-cap.service` | market_cap workers + universe apply |
| `theeye-macro.timer` | Mon–Fri 21:20 | `theeye-macro.service` | `workers.macro_pipeline` |
| `theeye-massive-ingest.timer` | Mon–Fri 21:30 | `theeye-massive-ingest.service` | `workers.massive_ingestion_worker` |
| `theeye-macro-refresh.timer` | Daily 21:30 | `theeye-macro-refresh.service` | macro refresh scripts |
| `theeye-daily-pipeline.timer` | Mon–Fri 21:35 | `theeye-daily-pipeline.service` | daily_pipeline + indicator validation |
| `theeye-sector.timer` | Mon–Fri 22:05 | `theeye-sector.service` | `workers.sector_aggregation_worker` |
| `theeye-supabase-sync.timer` | Mon–Fri 22:20 | `theeye-supabase-sync.service` | `workers.supabase_sync_worker --shadow` |
| `theeye-intraday-ingest.timer` | Mon–Fri 13:35–20:05 every 15m | `theeye-intraday-ingest.service` | `workers.intraday_ingestion_worker --once` |

## Appendix C — Compliance Rules Registry

From `services/compliance_service/src/compliance_service/rules/__init__.py`:

| Rule | File | Purpose |
|------|------|---------|
| RestrictedListRule | `restricted_list.py` | Block restricted symbols |
| MandateConstraintsRule | `mandate_constraints.py` | Portfolio mandate limits |
| WashSaleRule | `wash_sale.py` | Wash sale detection |
| PdtRule | `pdt_rule.py` | Pattern day trader rule |
| AmlStructuringRule | `aml_structuring.py` | AML structuring heuristics |

## Appendix D — Admin Service Routes (Complete)

### JSON API (all require JWT except noted)

**Auth** — `/admin/auth`

- `POST /admin/auth/login`
- `POST /admin/auth/refresh`
- `POST /admin/auth/logout`

**Orders** — `/admin/orders`

- `GET /admin/orders/pending`
- `GET /admin/orders/{order_id}`
- `POST /admin/orders/{order_id}/approve`
- `POST /admin/orders/{order_id}/reject`

**Audit** — `/admin/audit`

- `GET /admin/audit/log`
- `GET /admin/audit/verify`
- `GET /admin/audit/checkpoints`

**Agents** — `/admin/agents`

- `GET /admin/agents`
- `GET /admin/agents/{agent_id}/runs`
- `POST /admin/agents/{agent_id}/run`
- `GET /admin/agents/{agent_id}/constitution`

**Guard** — `/admin/guard`

- `GET /admin/guard/violations`
- `POST /admin/guard/violations/{violation_id}/resolve`

**Services** — `/admin/services` (JSON only, no UI page)

- `GET /admin/services/status`
- `POST /admin/services/{name}/restart`

**Backtest** — `/admin/backtest`

- `GET /admin/backtest`
- `POST /admin/backtest`
- `GET /admin/backtest/{backtest_id}/results`

**Costs** — `/admin/costs`

- `GET /admin/costs/daily`
- `GET /admin/costs/by-agent`

**SQL** — `/admin/sql`

- `POST /admin/sql/query`
- `POST /admin/sql/execute`

**Proposals** — `/admin/proposals`

- `GET /admin/proposals`
- `GET /admin/proposals/{proposal_id}`
- `POST /admin/proposals/{proposal_id}/approve`
- `POST /admin/proposals/{proposal_id}/reject`

### HTML pages (JWT required)

Nav items: Dashboard, Orders, Audit, Agents, Violations, Costs, SQL, Proposals.

See `services/admin_service/api/views.py` for full htmx fragment route list.

## Appendix E — Agent Directory (58 agents)

| Department | Count | Path |
|------------|-------|------|
| audit | 4 | `agents/audit/*.agent.md` |
| client | 3 | `agents/client/*.agent.md` |
| compliance | 9 | `agents/compliance/*.agent.md` |
| dev | 4 | `agents/dev/*.agent.md` |
| finance | 4 | `agents/finance/*.agent.md` |
| fundamental | 4 | `agents/fundamental/*.agent.md` |
| legal | 3 | `agents/legal/*.agent.md` |
| macro | 4 | `agents/macro/*.agent.md` |
| markets | 6 | `agents/markets/*.agent.md` |
| quant | 8 | `agents/quant/*.agent.md` |
| research | 7 | `agents/research/*.agent.md` |
| risk | 6 | `agents/risk/*.agent.md` |
| rnd | 1 | `agents/rnd/rnd_agent.agent.md` |
| top | 1 | `agents/top/master-orchestrator.agent.md` |

## Appendix F — Service Deployment Status

From `SERVICES_STATUS.md` (2026-06-15):

**Deployed:** `admin_service` (:7200), LiteLLM proxy (:4000), timer-driven workers, external Data API (sibling repo :7000).

**Not deployed (scaffold):** agent_runtime, audit_service (verify API only), backtest_engine, broker_adapter_alpaca, compliance_service, data_ingestion (optional), guard_service, master_orchestrator, oms, risk_service (staged), rnd_agent, snapshot_packager.

---

*Generated by backend-to-frontend control map audit, 2026-06-15.*
