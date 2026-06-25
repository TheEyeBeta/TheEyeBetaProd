# TheEyeBeta Backend -> Bloomberg-Terminal Frontend Control Map

**Date:** 2026-06-18  
**Stance:** fintech operator system, not a SaaS dashboard.  
**Bottom line:** The backend is broad and serious; the frontend is still narrow. `services/admin_service` now has a credible control-plane spine, including the new `MASTER_ADMIN` matrix, but most backend capabilities remain either JSON-only, CLI-only, systemd-only, or visible only through database tables. That is not acceptable for a production financial operating system.

---

## 1. Repository Map

| Area | Files / examples | Responsibility | Frontend status |
|---|---|---|---|
| Admin control plane | `services/admin_service/main.py`, `services/admin_service/api/*.py`, `services/admin_service/templates/*.html`, `services/admin_service/web.py` | JWT admin UI/API, htmx pages, RBAC, audit, SQL, services, workers, timers, trading halt | Best-covered area; still missing full pages for services, timers, workers, users, integrations |
| Data ingestion service | `services/data_ingestion/main.py`, `services/data_ingestion/src/data_ingestion/pipeline.py`, `adapters/{alpaca_data,cn_proxy,fred,news,yfinance}.py`, writers | Health/metrics, admin-triggered ingest, adapter pipeline, PG/Parquet writes | JSON/API only; no proper market-data operations page |
| Workers | `workers/base_worker.py`, `macro_ingestion_worker.py`, `macro_regime_worker.py`, `massive_ingestion_worker.py`, `intraday_ingestion_worker.py`, `indicator_compute_worker.py`, `theeyebeta_indicator_worker.py`, `sector_aggregation_worker.py`, `market_cap_fetch_worker.py`, `market_cap_threshold_worker.py`, `gap_sentinel_worker.py`, `latest_snapshot_worker.py`, `supabase_sync_worker.py`, `reporting_chain_worker.py`, `daily_pipeline_runner.py` | Scheduled ingestion, feature computation, sync, reporting, freshness/audit checks | `GET /admin/workers`, runs, manual trigger exist; no stop/pause/resume/config/log artifact UI |
| Agent runtime | `services/agent_runtime/main.py`, `src/agent_runtime/runner.py`, `snapshot_loader.py`, `guard_client.py`, `math_tool.py`; `agents/**/*.agent.md` | Runs agent constitutions against snapshots, records runs/messages/decisions, calls guard | Agents page covers list/runs/constitution/run; no disable/pause/config/version/rollback controls |
| Master orchestrator | `services/master_orchestrator/main.py`, `src/master_orchestrator/workflow.py`, `debate.py`, `clients.py`, `synthesis.py`, `consumer.py` | Market-trio workflow, multi-agent debate, order/proposal generation | Mostly invisible except downstream orders/proposals; no workflow console |
| Guard service | `services/guard_service/src/guard_service/app.py`, `validator.py`, `creative_classifier.py` | Validates agent outputs, writes guard violations, exposes HTTP/gRPC | Guard violations page exists; no guard policy/config controls |
| Risk service | `services/risk_service/src/risk_service/app.py`, `validator.py`, `models.py`, `metrics.py`; `cpp/include/zinc/risk/*.hpp` | Pre-trade validation, portfolio metrics, VaR/CVaR/correlation | Admin JSON `GET /admin/risk/metrics`, `POST /admin/risk/compute`; no serious Risk page |
| Compliance service | `services/compliance_service/src/compliance_service/app.py`, rule modules/tests | Pre-trade compliance checks: restricted list, mandate, PDT, AML/wash-sale style rules | Admin JSON checks only; no compliance workbench or rule editor |
| OMS | `services/oms/src/oms/app.py`, `reconciliation.py`, `state.py`; `cpp/include/zinc/oms/*.hpp` | Order state machine, approval, reconciliation pause/resolve | Admin proxy for reconciliation exists; no full OMS blotter/control page |
| Broker adapter | `services/broker_adapter_alpaca/src/broker_adapter_alpaca/app.py`, `consumer.py`, `streamer.py`, `live_gate.py` | Alpaca account/positions/orders, NATS fills, live gate | Broker status/positions proxied; no order/fill history UI, no integration control |
| Backtest engine | `services/backtest_engine/src/backtest_engine/app.py`, `runner.py`, `walk_forward.py`, `validation.py`, `metrics.py`, `parquet.py` | Run/status/results for backtests and validation runs | Backtest API exists; no full page except proposal validation fragments/dashboard button |
| Snapshot packager | `services/snapshot_packager/main.py`, `src/snapshot_packager/builder.py`, `consumer.py`, `writers.py`, `cli.py` | Build packaged snapshots, write object storage, NATS consumer | Not properly exposed; needs snapshot build/status/artifact UI |
| Audit service | `services/audit_service/src/audit_service/app.py`, `chain.py`, `consumer.py`, `export.py` | Hash-chain verification, WORM checkpoint/export | Audit page verifies/logs; export/checkpoint operations not exposed |
| RND agent | `services/rnd_agent/src/rnd_agent/app.py`, `runner.py`, `probe.py`, `email_digest.py` | Generates proposals under readonly role | Proposals page covers review; RND run/status not first-class |
| CLI operator console | `tb/tb/cli.py`, `tb/tb/commands/*.py` | Real operator surface for status, DB, workers, trask, prices, snapshots, prelive, deploy, secrets | Must become command palette/console; many commands have no UI equivalent |
| Scripts | `scripts/*.py`, `scripts/*.sh`, `scripts/macro_ingestor/*.py` | Backfills, migrations, prelive, audit verify, heartbeat, macro refresh, backup, secret rotation | Mostly backend-only/CLI-only; dangerous scripts need admin wrappers or explicit exclusion |
| Database | `db/migrations/versions/*.py`, `db/seeds/*.py`, `db/reference/*` | Canonical `theeyebeta` schema, seeds, grants, readonly views | SQL playground exists; schema explorer/permissions UI missing |
| Native C++ | `cpp/include/zinc/{risk,ta,opt,bt,oms}/*.hpp`, `cpp/bindings/*.cpp`, `libs/zinc_native/*` | Fast risk, technical analysis, optimization, backtest, OMS primitives | Invisible except through services/workers; should expose metrics/tests/version |
| Infra/deploy | `deploy/systemd/*.service`, `deploy/systemd/*.timer`, `infra/{grafana,prometheus,tempo,otelcol,caddy,cloudflared,k8s}` | Production process/timer definitions and observability | Timers/services status partial; no logs, no schedule editor, no infra health topology |
| Tests/docs | `tests/**`, `services/*/tests/**`, `docs/**`, `reports/**` | Verification, architecture, prior audits | CI-only; frontend should expose test/check status for operator readiness |

---

## 2. Backend Feature Registry

| Feature | Classification | Source files / symbols | Inputs | Outputs | What can go wrong | Frontend status / controls needed |
|---|---|---|---|---|---|---|
| Admin auth/session/MFA | Authentication/authorization | `services/admin_service/auth.py` routes `login`, `refresh`, `logout`, `logout/all`, `sessions`, `me`; `auth_mfa.py`; `rbac.py` | credentials, refresh cookie, JWT, TOTP | access tokens, sessions, role claim | stale sessions, weak role admin, missing user management | Login exists; needs Users/Permissions page for create/disable/role/session revoke |
| MASTER_ADMIN matrix | Admin/system control | `services/admin_service/api/master_admin.py`, `templates/master_admin.html` | JWT `MASTER_ADMIN` | matrix of controls/gaps | stale static registry if features change | Exists; must become Command Center source of truth |
| Ops pulse | Logging/monitoring | `api/ops.py`, `lib/queries/ops.py` | DB state, systemd summaries | health, breakers, alerts, stale heartbeats | false confidence if downstream missing | Dashboard/JSON exists; each item should deep-link to control surface |
| Orders approval | Trading function | `api/orders.py` functions `approve_pending_order`, `reject_pending_order`; `templates/orders.html` | order id, approve/reject body | DB state change, NATS `orders.approved.*`, audit | bad approval, race, missing OMS | Page exists; needs full order/fill lifecycle and cancel/replace |
| Live trading gate | Trading/emergency | `api/trading.py` `live_approval_token`, `live_approval`, `emergency_halt`; broker `live_gate.py` | confirmation token, reason, consequence ack | account metadata, Redis gate, NATS halt, audit | accidental live enable, partial Redis/NATS failure | API exists; needs red emergency frontend panel and current gate readback |
| OMS reconciliation | Portfolio/account logic | `api/oms.py`, `services/oms/src/oms/reconciliation.py`, `state.py` | drift state, resolve reason | reconciliation cleared, audit | resolving real drift without evidence | JSON proxy exists; needs OMS/Reconciliation page and stricter confirm |
| Broker account/positions/orders | External integration/trading | `api/broker.py`, `broker_adapter_alpaca/app.py` routes `/v1/account`, `/v1/positions`, `/v1/orders`, `/v1/orders/market` | Alpaca API, account/mode | positions, orders, fills | live broker failure, sync drift | partial status/positions; needs broker blotter, fill stream, integration controls |
| Workers | Data ingestion/processing | `api/workers.py`, `lib/worker_registry.py`, `workers/base_worker.py` subclasses | worker name, run args, date, dry_run/force | worker_runs, heartbeats, DB writes | duplicate runs, stale locks, partial writes | list/runs/manual run exists; needs stop/pause/resume/retry/config/logs |
| Timers | Task scheduling | `api/timers.py`, `deploy/systemd/*.timer` | unit name, trigger reason | systemd start, audit | schedule misfire, manual trigger collision | list/trigger exists; needs enable/disable/start/stop/schedule edit/journal |
| Services/systemd units | Admin/system control | `api/services.py`, `deploy/systemd/*.service` | service name, reason | systemctl restart, status | restarting critical infra blind | status/restart partial; needs start/stop/disable/logs/restart history |
| Trask breakers/components | Admin/system control | `api/trask.py`, `db/migrations/versions/0020_worker_ops.py` | breaker id, reason, override | breaker reset, audit | unsafe reset before recovery | dashboard/reset exists; needs component drilldown/config |
| Alerts | Observability/audit | `api/alerts.py`, `audit_alerts` | filters, ack note | acked alert | ack without owner/evidence | list/ack exists; needs assignment/escalation/SLA |
| Audit log/hash chain/checkpoints | Audit/compliance | `api/audit.py`, `audit_service/app.py`, `chain.py`, `export.py` | filters, verify range | audit rows, verify result, checkpoints | broken chain, unverifiable actions | page exists; needs immutable export/checkpoint controls |
| SQL playground | Database/security-sensitive | `api/sql.py` `run_select_statement`, `run_write_statement`; `templates/sql.html` | SQL, params, idempotency, confirm | query rows or write result, audit | data corruption, bypassing app logic | Exists; needs explain/dry-run/rollback helpers |
| Agents | Agent automation | `api/agents.py`, `agent_runtime/main.py`, `runner.py`, `agents/**/*.agent.md` | agent id, snapshot, prompt/kind | agent_runs/messages/decisions, costs | prompt abuse, guard failure, runaway cost | list/runs/run/constitution exists; needs disable/pause/config/versioning |
| Guard violations | Compliance/agent safety | `api/guard.py`, `guard_service/app.py`, `validator.py` | filters, resolve note | resolved violations/audit | weak resolve notes, untracked policy edits | page exists; needs policy editor and unresolved SLA |
| Proposals | Agent/research workflow | `api/proposals.py`, `rnd_agent/runner.py` | status/category/proposal id, review notes | approved/rejected proposal, validation backtest | approving weak evidence | page exists; needs rollback/supersede/defer persisted |
| Backtests | Market analysis/reporting | `api/backtest.py`, `backtest_engine/app.py`, `runner.py` | strategy, date range, universe | run status/results/artifacts | expensive jobs, stale data | API exists; needs full run console/cancel/retry/artifacts |
| Costs | Reporting/observability | `api/costs.py`, `model_runs`, `api_costs` | days/month | spend charts/tables | unbounded LLM/vendor spend | page exists; needs budgets/alerts/kill integration |
| Briefings/reports | Reporting | `api/briefings.py`, `workers/reporting_chain_worker.py`, `agent_reports` | market, generated reports | briefings list | stale/missing chain-of-command | page exists; needs schedule/status/report artifact controls |
| Risk metrics | Risk calculation | `api/risk.py`, `risk_service/app.py`, `scripts/risk_metrics_refresh.py`, C++ risk | portfolio/orders | risk_metrics, validation result | empty portfolio, stale metrics | JSON only; build Risk cockpit |
| Compliance checks | Legal/compliance | `api/compliance.py`, `compliance_service/app.py` | order check payload | compliance_checks | missing legal rule config | JSON only; build Compliance cockpit |
| Data ingestion service | Data ingestion | `data_ingestion/main.py` `/ingest/run`, `pipeline.py`, adapters | source/date/adapters | prices, macro, news, fundamentals | vendor outage, duplicate/dirty data | no page; build Market Data/Data Pipelines pages |
| Snapshot packaging | Data processing | `snapshot_packager/main.py`, `builder.py`, `consumer.py` | market/date | packaged snapshot, MinIO/DB row | corrupt/incomplete snapshot | no page; build Snapshot Operations |
| Macro ingest/refresh | Data ingestion | `workers/macro_ingestion_worker.py`, `macro_regime_worker.py`, `scripts/macro_ingestor/*` | FRED/yfinance/manual files | macro_indicators, regimes | stale macro, file mistakes | worker/timer partial; macro-specific UI missing |
| Prices/intraday | Market data | `massive_ingestion_worker.py`, `intraday_ingestion_worker.py`, `latest_snapshot_worker.py`, `prices_*` | exchange/date/provider | daily/intraday/latest snapshots | gaps, provider throttling | worker partial; market-data quality UI missing |
| Indicators/sector/features | Data processing/signal support | `indicator_compute_worker.py`, `theeyebeta_indicator_worker.py`, `sector_aggregation_worker.py`, `ind_technical_daily`, `sector_daily` | prices/date | indicators/sectors | bad calculations, stale indicators | no feature-specific UI |
| Market cap/universe | Data processing/config | `market_cap_fetch_worker.py`, `market_cap_threshold_worker.py`, `scripts/select_universe_by_cap.py`, `market_cap_daily`, `audit_cap_events` | provider/date/tier | universe changes, cap events | universe drift | no universe-control UI |
| Supabase sync | External integration | `supabase_sync_worker.py`, `scripts/inventory_supabase_sync.py` | snapshots/tables | Supabase stock_snapshots | public sync corruption | no integration page |
| Secrets/config | Security/config | `tb/tb/commands/secrets.py`, `scripts/rotate_secrets.sh`, `config/litellm.yaml`, `.env*` | sops/env/config | credentials/config state | secret exposure | backend-only raw secrets; expose only redacted rotate/test |
| Database migrations/seeds | Database/storage | `db/migrations/versions/*.py`, `db/seeds/*.py`, `scripts/db-migrate.sh` | alembic revision/seed args | schema/data | destructive migration | no UI; should show migration status/read-only, not arbitrary run |
| Infra/observability | Logging/monitoring | `infra/prometheus`, `infra/grafana/dashboards/*.json`, `infra/tempo`, `infra/caddy`, `cloudflared` | metrics/logs/traces | dashboards/tunnels | blind outage | Grafana iframe only; needs service topology/logs |
| Native engines | Risk/TA/BT/OMS/opt | `cpp/include/zinc/**`, `cpp/bindings/*.cpp`, `libs/zinc_native/*` | arrays/orders/snapshots | fast calculations | silent ABI/math regression | no direct UI; expose version/bench/test status |

---

## 3. Frontend Module Map

| Module | Purpose | Backend links |
|---|---|---|
| Command Center / Home | One-screen operational status and command entry | `/admin/ops/pulse`, `/admin/master-admin/control-matrix`, WS `/admin/events/stream` |
| Admin / System Control | Owner matrix, services, timers, workers, kill switches | `api/master_admin.py`, `api/services.py`, `api/timers.py`, `api/workers.py`, `api/trading.py` |
| Market Data | Prices, intraday, macro, news, fundamentals, universe, gaps | workers, `data_ingestion`, `prices_daily`, `prices_intraday`, `macro_indicators`, `news_articles` |
| Data Pipelines | Worker/timer runs, retries, logs, data quality | `worker_runs`, `worker_heartbeats`, `audit_data_gaps`, `audit_alerts` |
| Risk | Metrics, limit checks, risk-service health, overrides | `/admin/risk/*`, `risk_service`, `risk_metrics` |
| Legal / Compliance | Compliance checks, restricted/mandate rules, exceptions | `/admin/compliance/checks`, `compliance_service`, `compliance_checks` |
| Audit | Audit log, hash chain, checkpoints, WORM export | `/admin/audit/*`, `audit_service` |
| Agents | Registry, runs, constitutions, messages, cost, disable/pause | `/admin/agents/*`, `agent_runtime`, `agents/**/*.agent.md` |
| Signals / Recommendations | Signals, proposals, agent decisions, validation | `signals`, `proposals`, `agent_decisions`, backtests |
| Portfolio / Positions | Accounts, portfolios, positions, executions, broker | broker adapter, OMS, trading tables |
| Orders / OMS | Order lifecycle, approvals, fills, reconciliation | `/admin/orders/*`, `/admin/oms/*`, NATS broker events |
| Backtests / Research | Backtest run lifecycle, artifacts, validation | `/admin/backtest*`, `backtest_engine` |
| Reports / Briefings | Chain-of-command briefings, generated reports | `/admin/briefings`, `agent_reports`, reporting worker |
| Costs | LLM/API spend, budgets, kill thresholds | `/admin/costs/*`, `model_runs`, `api_costs` |
| Users / Permissions | Admin users, roles, sessions, MFA | `admin_users`, `admin_roles`, `auth.py`, `auth_mfa.py` |
| Settings / Integrations | Redacted vendor/broker/LLM/storage config and tests | config/secrets/adapters, LitellM, Alpaca, Supabase, MinIO |
| CLI / Command Console | UI equivalents of `tb` command tree and safe scripts | `tb/tb/commands/*.py`, `scripts/*.py` |

---

## 4. Page-by-Page Specification

| Page | Purpose | Data displayed | User controls | Required APIs/backend changes |
|---|---|---|---|---|
| Command Center | Dense Bloomberg-style operator home | health, open breakers, critical alerts, stale heartbeats, pending orders, spend, audit-chain status | command palette, quick actions, emergency halt | Extend `/admin/ops/pulse` deep links; add current trading gate readback |
| MASTER_ADMIN | System-owner truth table | control matrix, gaps, dangerous actions | view gap details, jump to modules | Exists: `/admin/master-admin`; keep matrix updated |
| Services | Process topology | systemd unit state, uptime, restarts, logs | restart/start/stop/disable with confirm | Add start/stop/disable/log/history endpoints |
| Workers / Schedulers | Job operations | registry, run history, inputs/outputs, logs, timers | trigger, retry, pause, resume, stop, edit schedule/config | Add cooperative cancellation, config CRUD, journal/log artifacts |
| Market Data | Data quality terminal | prices, intraday buckets, gaps, provider status, universe | backfill, rerun provider, mark gap resolved | Wrap existing workers/scripts safely; expose quality tables |
| Risk | Risk cockpit | exposures, VaR/CVaR, breaches, stale metrics, risk service health | compute, override, lock trading | Add limit config/versioning and override endpoints |
| Legal / Compliance | Compliance cockpit | checks, restricted rules, mandate breaches, exceptions | re-check, override, edit rule, legal hold | Add rule CRUD, exception workflow, audit payloads |
| Audit | Chain and action history | audit log, verify result, checkpoints, alerts | verify, export, checkpoint, filter | Add immutable export/checkpoint controls if required |
| Agents | Agent ops | agents, runs, constitutions, messages, violations, cost | run, pause, disable, edit/version constitution | Add lifecycle/config/version endpoints |
| Proposals / Signals | Recommendations review | proposals, signal status, validation backtest | approve/reject/defer/supersede/rollback | Add persisted defer/supersede/rollback |
| Orders / OMS | Trading blotter | pending/live orders, state transitions, fills, reconciliation | approve/reject/cancel/replace/resolve | Add full OMS/broker history proxies |
| Portfolio / Positions | Book view | accounts, portfolios, positions, executions, broker account | refresh, reconcile, export | Add account/portfolio/position read APIs |
| Backtests | Research job terminal | runs, params, status, metrics, artifacts | start, cancel, retry, compare, export | Add cancel/retry/artifact browser |
| Reports / Briefings | Staff reporting | chain reports, generated summaries, stale/missing reports | regenerate, approve, export | Add report run controls and artifact download |
| Costs | Spend control | daily spend, by-agent/vendor, budgets | set budget, disable high-cost agent/model | Add budget/threshold enforcement |
| Users / Permissions | RBAC admin | users, roles, MFA, sessions | create/disable, grant/revoke, revoke sessions | Add safe admin-user/role APIs |
| Settings / Integrations | Redacted config | provider status, key present/age, endpoints, modes | test, rotate, enable/disable | Add redacted config/status/rotate/test endpoints; never reveal secrets |
| CLI Console | Command-driven workflows | command catalog, recent commands, output | run approved commands, save macros | Build allowlisted command API with audit and confirmation |

Every page needs: loading/empty/error states, audit trail drawer, raw input/output panel for jobs, role badges, and keyboard-driven command entry.

---

## 5. Master Control Matrix

| Backend feature | File/source | Frontend location | Viewable? | Controllable? | Editable? | Schedulable? | Kill switch? | Confirm? | Role | Audit? | API exists? | Missing backend work | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ops pulse | `api/ops.py` | Command Center | yes | no | no | no | no | no | READ_ONLY | no | yes | Deep links and remediation actions | Critical |
| MASTER_ADMIN matrix | `api/master_admin.py` | Admin/System Control | yes | no | no | no | no | no | MASTER_ADMIN | no | yes | Keep registry generated/complete | Critical |
| Auth sessions | `auth.py`, `auth_mfa.py` | Users/Permissions | partial | partial | no | no | yes | yes | MASTER_ADMIN | yes | partial | User/role/session CRUD | Critical |
| Workers | `api/workers.py`, `workers/*.py` | Workers/Schedulers | yes | trigger only | no | no | yes | yes | OPERATOR/MASTER_ADMIN | yes | partial | stop/pause/resume/retry/config/logs | Critical |
| Timers | `api/timers.py`, `deploy/systemd/*.timer` | Workers/Schedulers | yes | trigger only | no | no | yes | yes | OPERATOR/MASTER_ADMIN | yes | partial | enable/disable/schedule edit/journal | Critical |
| Services | `api/services.py`, `deploy/systemd/*.service` | Services | yes | restart only | no | no | yes | yes | OPERATOR/MASTER_ADMIN | yes | partial | start/stop/disable/logs | Critical |
| Trading live gate | `api/trading.py` | Trading/Emergency | partial | yes | yes | no | yes | yes | MASTER_ADMIN | yes | yes | current gate status/resume workflow | Critical |
| Orders | `api/orders.py` | Orders/OMS | yes | approve/reject | no | no | yes | yes | OPERATOR | yes | partial | cancel/replace/fill lifecycle | Critical |
| OMS reconciliation | `api/oms.py`, `services/oms` | Orders/OMS | yes | resolve | no | no | yes | yes | MASTER_ADMIN | yes | partial | stronger confirmation/history | Critical |
| Broker adapter | `api/broker.py`, `broker_adapter_alpaca` | Portfolio/Broker | partial | no | no | no | yes | yes | ANALYST/MASTER_ADMIN | yes | partial | orders/fills/history/integration controls | Critical |
| Risk | `api/risk.py`, `risk_service` | Risk | yes | compute only | no | schedule via timer | yes | yes | OPERATOR/MASTER_ADMIN | yes | partial | limit config/override/failure history | Critical |
| Compliance | `api/compliance.py`, `compliance_service` | Legal/Compliance | checks only | no | no | no | yes | yes | COMPLIANCE/MASTER_ADMIN | yes | partial | rule CRUD/recheck/override | Critical |
| Audit | `api/audit.py`, `audit_service` | Audit | yes | verify/ack | no | audit-verify timer | no | yes | COMPLIANCE | yes | partial | export/checkpoint/assignment | Critical |
| Alerts | `api/alerts.py` | Alerts | yes | ack | no | no | no | yes | OPERATOR | yes | yes | owner/escalation/SLA | High |
| Agents | `api/agents.py`, `agent_runtime`, `agents/**` | Agents | yes | run | no | no | yes | yes | OPERATOR/MASTER_ADMIN | yes | partial | pause/disable/config/version | High |
| Guard | `api/guard.py`, `guard_service` | Violations | yes | resolve | no | no | yes | yes | OPERATOR | yes | partial | guard policy controls | High |
| Proposals | `api/proposals.py`, `rnd_agent` | Proposals/Signals | yes | approve/reject | no | no | no | yes | OPERATOR | yes | partial | persisted defer/supersede/rollback | High |
| Backtests | `api/backtest.py`, `backtest_engine` | Backtests | yes | start | no | no | no | yes | OPERATOR | yes | partial | cancel/retry/artifacts/logs | High |
| Costs | `api/costs.py` | Costs | yes | no | no | no | yes | yes | ANALYST/MASTER_ADMIN | yes | partial | budgets/threshold kill | High |
| Briefings | `api/briefings.py`, `reporting_chain_worker.py` | Reports | yes | no | no | timer only | no | yes | READ_ONLY/OPERATOR | yes | partial | regenerate/export/status | Medium |
| Data ingestion | `data_ingestion/main.py`, workers | Market Data | partial | partial | no | timer only | yes | yes | OPERATOR | yes | partial | provider controls/data quality UI | Critical |
| Snapshot packaging | `snapshot_packager/main.py` | Snapshots | no | no | no | NATS only | no | yes | OPERATOR | yes | partial | build/status/artifacts page | High |
| Market cap/universe | `market_cap_*`, `select_universe_by_cap.py` | Universe | partial | CLI/worker | partial | timer | yes | yes | MASTER_ADMIN | yes | no | universe editor/audit workflow | High |
| Supabase sync | `supabase_sync_worker.py` | Integrations | no | timer/worker | no | timer | yes | yes | MASTER_ADMIN | yes | no | redacted status/test/disable | High |
| Secrets/config | `tb/tb/commands/secrets.py`, `config/litellm.yaml` | Settings | no | CLI-only | CLI-only | no | yes | yes | MASTER_ADMIN | yes | no | safe redacted rotate/test; raw secrets backend-only | Critical |
| DB migrations/seeds | `db/migrations`, `db/seeds` | Database | partial | CLI-only | yes via SQL | no | yes | yes | MASTER_ADMIN | yes | partial | migration status/guarded apply | High |
| Native engines | `cpp/**`, `libs/zinc_native/**` | Observability | no | no | no | no | no | no | READ_ONLY | no | no | expose version/bench/test status | Medium |

---

## 6. Missing API List

Critical missing APIs:

- `GET/PATCH /admin/users`, `/admin/users/{id}/roles`, `/admin/users/{id}/sessions`, `/admin/users/{id}/disable`
- `POST /admin/workers/{name}/stop`, `/pause`, `/resume`, `/retry/{run_id}`, `GET/PATCH /admin/workers/{name}/config`, `GET /admin/workers/{name}/logs`
- `POST /admin/timers/{name}/enable|disable|start|stop`, `PATCH /admin/timers/{name}/schedule`, `GET /admin/timers/{name}/journal`
- `POST /admin/services/{name}/start|stop|disable|enable`, `GET /admin/services/{name}/logs`, `GET /admin/services/{name}/history`
- `GET /admin/trading/status`, `POST /admin/trading/resume-from-halt`
- `GET /admin/orders/{id}/events`, `POST /admin/orders/{id}/cancel|replace`
- `GET /admin/broker/orders`, `/fills`, `/account`, `POST /admin/broker/test-connection`
- `GET/PATCH /admin/risk/limits`, `POST /admin/risk/override`, `GET /admin/risk/failures`
- `GET/PATCH /admin/compliance/rules`, `POST /admin/compliance/recheck`, `POST /admin/compliance/override`
- `POST /admin/backtest/{id}/cancel`, `/retry`, `GET /admin/backtest/{id}/artifacts`
- `GET /admin/integrations`, `POST /admin/integrations/{name}/test|disable|rotate`
- `GET /admin/db/migrations`, `POST /admin/db/migrations/apply` with confirmation and dry-run
- `POST /admin/commands/run` for an audited allowlist of CLI-equivalent commands

Backend-only with strong reason:

- Raw secrets from `.env*`, `secrets/`, and sops files must never be viewable in the frontend, even by `MASTER_ADMIN`. Expose rotate/test/disable workflows only.
- Direct arbitrary shell execution should stay backend-only. The UI may run audited allowlisted commands, not free-form shell.
- Native C++ internals should not be user-controllable. Expose version, benchmark, and test health instead.

---

## 7. Security, Risk, Audit Concerns

- The system has RBAC now, but RBAC administration is missing. That is weak: a production admin plane without user/role/session management forces operators back to SQL/scripts.
- Workers and timers can be triggered but not safely stopped or paused. That is operationally dangerous during vendor incidents or bad data.
- Service restart exists for a small whitelist, but logs/history are missing. Restarting blind is amateur hour in a financial system.
- Compliance is observational only. There is no safe rule editor, exception workflow, or legal hold control.
- Risk has compute/read surfaces but no real limit-management lifecycle. A risk dashboard without limit versioning is not a risk control plane.
- SQL write is powerful and audited, but it is still a broad escape hatch. Build purpose-specific admin APIs so SQL is not the normal way to operate.
- Broker/OMS controls are incomplete. Live trading needs current gate state, fills, order events, cancel/replace, and reconciliation evidence before resolve.
- Secrets must stay non-readable. `MASTER_ADMIN` can own secrets by rotating/testing/locking them, not by seeing raw values.
- Audit chain exists, but manual export/checkpoint/incident evidence workflows are not complete.

---

## 8. Bloomberg-Terminal UX Recommendations

- Use a command-first shell: `Ctrl+K` opens commands like `WORKER RUN macro-ingestion --date`, `HALT TRADING`, `AUDIT VERIFY 24H`, `ORDER 123 APPROVE`.
- Keep the first viewport dense: health strip, market clock, open breakers, pending orders, stale jobs, trading gate, audit-chain status.
- Every mutating command opens a consequence preview: target, blast radius, expected events, rollback/compensating action, required role, audit payload.
- Tables should dominate: sortable, filterable, keyboard navigable, live-updating. Cards are only for summaries and repeated artifacts.
- Every job/run/order has the same drilldown pattern: Inputs, Outputs, Logs, Failures, Audit Trail, Retry/Stop/Resume.
- Use color sparingly: red for dangerous/failed, amber for degraded/pending, green for verified/completed, blue/neutral for informational.
- Make CLI parity explicit: each UI command should show the equivalent `tb ...` or backend command where safe.

---

## 9. Implementation Backlog

### Critical

| Task | Why it matters | Backend files | Frontend module | Acceptance criteria |
|---|---|---|---|---|
| Build Users/Permissions | RBAC cannot be operated safely today | `auth.py`, `auth_mfa.py`, `rbac.py`, `0026_admin_rbac.py` | Users/Permissions | create/disable users, assign/revoke roles, revoke sessions, all audited |
| Build Workers/Schedulers page | Core data jobs are only partially controllable | `api/workers.py`, `api/timers.py`, `workers/*` | Workers/Schedulers | registry, runs, timers, trigger/retry, logs, missing controls visible |
| Add worker stop/pause/resume/retry APIs | Trigger-only control is insufficient | `workers/base_worker.py`, `api/workers.py` | Workers/Schedulers | cooperative cancellation and run-id retry with audit |
| Build Services page with logs | Restart without logs is blind | `api/services.py`, systemd units | Services | status, restart, logs, history; stop/disable MASTER_ADMIN-only |
| Build Emergency Trading panel | Live control must be obvious and safe | `api/trading.py`, broker `live_gate.py` | Trading/Emergency | current gate state, halt/resume, consequence preview, audit trail |
| Build Risk cockpit | Risk is not a table; it is a control system | `api/risk.py`, `risk_service` | Risk | metrics, stale status, breaches, compute, limit config gap visible |
| Build Compliance cockpit | Legal controls are underexposed | `api/compliance.py`, `compliance_service` | Legal/Compliance | checks, rule status, overrides gap visible |
| Build OMS/Broker blotter | Trading cannot be supervised from pending orders alone | `api/orders.py`, `api/oms.py`, `api/broker.py` | Orders/Portfolio | order events, fills, positions, reconciliation evidence |

### High

| Task | Why it matters | Backend files | Frontend module | Acceptance criteria |
|---|---|---|---|---|
| Backtest console | Validation jobs need lifecycle control | `api/backtest.py`, `backtest_engine` | Backtests | start/status/results/cancel/retry/artifacts |
| Agent lifecycle controls | Agent runtime has run/read but no disable/config | `api/agents.py`, `agent_runtime`, `agents/**` | Agents | pause/disable/config version visible, audit |
| Integration status/rotate/test | External integrations are operational risk | adapters, broker, Supabase, LiteLLM config | Settings | redacted status, test, disable, rotate workflows |
| Market Data quality page | Data quality drives all outputs | workers, `data_ingestion`, `audit_data_gaps` | Market Data | gap tables, provider status, rerun controls |
| Audit export/checkpoint | Regulated evidence needs export | `audit_service/export.py`, `api/audit.py` | Audit | immutable export and checkpoint workflow |

### Medium

| Task | Why it matters | Backend files | Frontend module | Acceptance criteria |
|---|---|---|---|---|
| CLI command console | Operators already use `tb` | `tb/tb/commands/*.py` | CLI Console | allowlisted commands, audit, output capture |
| Native engine health | C++ regressions can silently affect outputs | `cpp/**`, `libs/zinc_native/**` | Observability | versions, benchmarks, test status |
| Report artifact browser | Briefings/reports need auditability | `briefings.py`, `reporting_chain_worker.py` | Reports | list, regenerate, export, audit |

### Low

| Task | Why it matters | Backend files | Frontend module | Acceptance criteria |
|---|---|---|---|---|
| Keyboard shortcut layer | Faster operator workflows | frontend shell | All pages | documented shortcuts, no conflicts |
| Saved views/layouts | Bloomberg-style personalization | frontend/storage | All tables | per-user filters and column layouts |

---

## 10. Top 20 Frontend Features To Build First

1. Users/Permissions page with role assignment and session revocation.
2. Trading emergency panel: current gate state, halt, resume, audit trail.
3. Workers/Schedulers page with run history, logs, trigger, retry, and missing-control flags.
4. Worker stop/pause/resume/retry backend APIs.
5. Services page with systemd logs and restart/start/stop controls.
6. Risk cockpit with stale metrics, breaches, and compute controls.
7. Compliance cockpit with checks, rules status, and override workflow.
8. OMS/Broker blotter with orders, fills, positions, reconciliation evidence.
9. Market Data quality page: gaps, provider status, ingestion freshness.
10. Backtest console with cancel/retry/artifacts.
11. Agent lifecycle controls: pause, disable, config/constitution versions.
12. Audit export/checkpoint workflow.
13. Integration status page with redacted test/rotate/disable.
14. Costs budget controls and kill thresholds for LLM/vendor spend.
15. Proposal supersede/rollback/persisted defer.
16. Snapshot operations page for packaged snapshots and artifacts.
17. Universe/market-cap control page with audit-cap events.
18. Command palette backed by audited allowlisted actions.
19. CLI-equivalent console for safe `tb` commands.
20. Native engine/version/benchmark observability panel.

---

## Brutal Gap Summary

The repo has the bones of a serious financial operating system. The frontend does not yet match the backend’s blast radius. The most dangerous mismatch is that backend processes can mutate data, trigger trading workflows, alter risk/compliance outputs, and schedule jobs while the frontend only exposes a fraction of their lifecycle. The new `MASTER_ADMIN` matrix is the right start because it tells the truth. The next step is to turn every “partial” row into either a real audited control or an explicitly justified backend-only operation.
