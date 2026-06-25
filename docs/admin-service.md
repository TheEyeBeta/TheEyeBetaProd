# Admin Service

> **The Eye Terminal:** Official architecture direction — [the-eye-terminal-architecture.md](the-eye-terminal-architecture.md)
>
> Port **7200** — Tailscale (`0.0.0.0`) and Cloudflare (`https://admin.theeyebeta.store`).
> JWT RS256 auth (`POST /admin/auth/login`); refresh token in httpOnly cookie.
> See [architecture.md §9](architecture.md#9-admin-service) and
> [.cursor/rules/frontend-htmx.mdc](../.cursor/rules/frontend-htmx.mdc).

## Stack

- **Jinja2** templates rendered server-side by FastAPI
- **htmx** for most interactive elements (forms, fragments, polling)
- **Minimal page-scoped JavaScript** on Command Console (`/admin/console`) for preview/run `fetch` calls only
- **Tailwind CSS** via CDN (no build step)
- **Chart.js** for data visualisation (loaded from CDN, initialised via `data-chart` attributes)

### Local development (admin-service)

Requires **PostgreSQL**, **Redis**, and **NATS** on startup.

**UI source:** `TheEyeBetaAdminFrontend/` (templates, static, `frontend_ia`). Override with `ADMIN_FRONTEND_ROOT` in `.env`.

```powershell
# From repo root — start Docker Desktop first, then:
cd TheEyeProd
docker compose --env-file .env up postgres redis nats -d

# Run migrations if needed (from repo root with venv active):
.venv\Scripts\python.exe -m alembic -c db/alembic.ini upgrade head

# Start admin-service (port 7200):
cd services\admin_service
..\..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 7200
```

Health check: `GET http://127.0.0.1:7200/admin/health` → `{"status":"ok",...}`.

## Pages

| Page | Route | Purpose |
|------|-------|---------|
| Command Center | `/admin/` | Dashboard, quick actions |
| MASTER_ADMIN | `/admin/master-admin` | Control matrix + drift/staleness alerts |
| Cloudflare / Edge | `/admin/edge` | Tunnel status, DNS routes, drift |
| Edge Routes | `/admin/edge/routes` | Canonical route registry + probes |
| Data API | `/admin/data-api` | Public hostnames, ports, trusted hosts |
| Command Console | `/admin/console` | Allowlisted CLI parity (MASTER_ADMIN) |
| Workers | `/admin/workers` | Worker/timer registry and control |
| Services | `/admin/services` | systemd allowlist, port ownership |
| Emergency Trading | `/admin/emergency` | Halt, resume, live approval |
| Orders | `/admin/orders` | OMS blotter |
| Users/Permissions | `/admin/users` | MASTER_ADMIN RBAC |

### Information architecture (P-FE-IA)

Navigation is generated from `frontend_ia/modules.py` (26 modules) and validated against the MASTER_ADMIN control matrix. Sidebar groups: **Ops**, **Edge**, **Trading**, **Compliance**, **Data**, **Platform**.

- **Shipped pages** show a module status strip (role, API route, completeness, matrix row count).
- **Shell pages** (`/admin/integrations`, `/admin/observability`) surface planned work from the matrix; all other modules are shipped cockpits.
- **Role filtering**: JWT `roles` claim (default `operator`); `MASTER_ADMIN` sees Users/Permissions, Emergency Trading, CLI/Console.
- **Keyboard**: `g` then `c` (Command Center), `m` (MASTER_ADMIN), `e` (Edge), `o` (Orders).

### Orders API (P-AD-R-orders)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/orders/pending` | Bearer JWT | Pending-approval queue (joined to instruments) |
| `GET` | `/admin/orders/{id}` | Bearer JWT | Order detail |
| `POST` | `/admin/orders/{id}/approve` | Bearer JWT (20/min) | `pending_approval` → `approved`; NATS `orders.approved.{id}` |
| `POST` | `/admin/orders/{id}/reject` | Bearer JWT (20/min) | → `rejected`; `metadata.rejection_reason` set |

### Audit API (P-AD-R-audit)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/audit/log` | Bearer JWT | Paginated `audit_log` (`entity_id`, `actor`, `since`, `limit`, `cursor`) |
| `GET` | `/admin/audit/verify` | Bearer JWT | Proxies audit-service `GET /audit/verify?from=&to=` → `{ok, mismatch_at_id?}` |
| `GET` | `/admin/audit/checkpoints` | Bearer JWT | Lists `audit_checkpoints` rows (newest first) |

### Agents API (P-AD-R-agents)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/agents` | Bearer JWT | Registry + last-run / 7-day success-rate aggregates |
| `GET` | `/admin/agents/{id}/runs` | Bearer JWT | Newest-first `agent_runs` rows (default `limit=50`, max 200) |
| `POST` | `/admin/agents/{id}/run` | Bearer JWT (20/min) | Forwards to `agent-runtime POST /agents/{id}/run`; audit logs `run.agent` |
| `GET` | `/admin/agents/{id}/constitution` | Bearer JWT | Returns the agent's constitution markdown from disk |

### Guard API (P-AD-R-guard)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/guard/violations` | Bearer JWT | Paginated `guard_violations` (`agent_id`, `severity`, `unresolved_only`, `limit`, `cursor`) |
| `POST` | `/admin/guard/violations/{id}/resolve` | Bearer JWT (20/min) | Sets `resolved=true`, `resolved_by=admin-api:<sub>`, `resolved_at=now`; audit logs `resolve.guard_violation` |

### Services API (P-AD-R-services)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/services/status` | Bearer JWT | Lists Docker containers attached to `theeyebeta-net` (name, image, state, health, uptime) |
| `POST` | `/admin/services/{name}/restart` | Bearer JWT (20/min) | Restarts a whitelisted service container; audit logs `restart.service` |

### Cloudflare / Edge API

Read-only edge control plane. Never returns raw `.env`, Cloudflare tokens, or secret values — only `credentials_present: true/false`. Uses **local/dummy mode** when `CLOUDFLARE_API_TOKEN` is absent (`EDGE_MODE=auto|local|live`).

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/cloudflare/status` | Bearer JWT | Aggregate CF/tunnel/WAF/DNS status + missing setup steps |
| `GET` | `/admin/cloudflare/tunnels` | Bearer JWT | Tunnel health summary |
| `GET` | `/admin/cloudflare/access/apps` | Bearer JWT | Access policy presence (local stub when no token) |
| `GET` | `/admin/cloudflare/dns/routes` | Bearer JWT | Public hostnames from cloudflared config |
| `GET` | `/admin/cloudflare/waf/events` | Bearer JWT | WAF/rate-limit status (local stub when no token) |
| `POST` | `/admin/cloudflare/test` | Bearer JWT | Non-mutating connectivity probe; audit logged |
| `GET` | `/admin/cloudflare/routes` | Bearer JWT | Alias of edge route list |
| `GET` | `/admin/cloudflare/routes/drift` | Bearer JWT | Alias of edge drift report |
| `GET` | `/admin/edge/routes` | Bearer JWT | Edge Route Registry — canonical rows + live probes |
| `GET` | `/admin/edge/routes/{hostname}` | Bearer JWT | Single route detail |
| `GET` | `/admin/edge/routes/drift` | Bearer JWT | Drift alerts (tunnel port, trusted host, health) |
| `POST` | `/admin/edge/routes/check` | Bearer JWT | Refresh probes; audit logged |
| `GET` | `/admin/edge/ports` | Bearer JWT | Registered vs listening ports |
| `GET` | `/admin/edge/trusted-hosts` | Bearer JWT | Hostname allowlist presence (hostnames only) |

Known Data API routes (shared backend on `:7000` until split):

- `dataapi.theeyebeta.store` → `127.0.0.1:7000` `/health`
- `dataapiprod.theeyebeta.store` → `127.0.0.1:7000` `/health` (same service — intentional shared backend)

Port **9500** is flagged as unregistered incident sentinel if seen in tunnel config.

### Command Console API (allowlisted CLI parity)

No arbitrary shell — commands map to existing control-plane APIs only. Dangerous commands require `{reason, confirm: true}` and `X-Confirm: true`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/commands` | Bearer JWT | Allowlisted command registry |
| `POST` | `/admin/commands/preview` | Bearer JWT | Consequence preview (audited preview row) |
| `POST` | `/admin/commands/run` | Bearer JWT | Execute mapped backend API |
| `GET` | `/admin/commands/runs` | Bearer JWT | Run history |
| `GET` | `/admin/commands/runs/{id}` | Bearer JWT | Run detail + audit link |
| `GET` | `/admin/console` | Bearer JWT | HTML command palette (minimal JS for preview/run) |

### Control matrix staleness (CI guard)

`control_matrix/staleness.py` compares workers, services, timers, commands, nav modules, and canonical edge routes against `GET /admin/master-admin/control-matrix`. Violations surface as `STALENESS:` drift alerts and fail unit tests (`tests/test_control_matrix.py`). Dynamic FastAPI route discovery is planned; static `expected_registry.py` is the guard today.

### Users / Permissions API (MASTER_ADMIN)

DB-backed operator RBAC. Never returns `password`, `password_hash`, or MFA secrets. Dangerous mutations require JSON `{reason, confirm: true}` and header `X-Confirm: true`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/users` | MASTER_ADMIN | List users (JSON) or HTML page (`Accept: text/html`) |
| `GET` | `/admin/users/{id}` | MASTER_ADMIN | User detail + audit history (redacted payloads) |
| `POST` | `/admin/users` | MASTER_ADMIN | Create user with bcrypt password + initial roles |
| `PATCH` | `/admin/users/{id}` | MASTER_ADMIN | Update display name / email |
| `POST` | `/admin/users/{id}/disable` | MASTER_ADMIN | Disable user + revoke sessions (dangerous) |
| `POST` | `/admin/users/{id}/enable` | MASTER_ADMIN | Re-enable user (dangerous) |
| `GET` | `/admin/users/{id}/roles` | MASTER_ADMIN | List role names |
| `POST` | `/admin/users/{id}/roles` | MASTER_ADMIN | Grant role (dangerous; MASTER_ADMIN grant requires MASTER_ADMIN) |
| `DELETE` | `/admin/users/{id}/roles/{role}` | MASTER_ADMIN | Revoke role (dangerous; blocks last MASTER_ADMIN unless `allow_final_master_removal`) |
| `GET` | `/admin/users/{id}/sessions` | MASTER_ADMIN | Active/revoked session metadata (no tokens) |
| `POST` | `/admin/users/{id}/sessions/revoke` | MASTER_ADMIN | Revoke all sessions (dangerous) |
| `POST` | `/admin/users/{id}/mfa/reset` | MASTER_ADMIN | Reset MFA enrollment (dangerous) |

Login (`POST /admin/auth/login`) loads roles from DB when the user exists and embeds them in the JWT `roles` claim.

### Backtest API (P-AD-R-backtest)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/backtest` | Bearer JWT | Recent runs from `backtest_runs` (default `limit=50`, max 200) |
| `POST` | `/admin/backtest` | Bearer JWT (20/min) | Forwards to `backtest-engine POST /backtest/run`; audit logs `start.backtest` |
| `GET` | `/admin/backtest/{id}/results` | Bearer JWT | Proxies `backtest-engine GET /backtest/{id}/results` (404/409 surface unchanged) |

### Costs API (P-AD-R-costs)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/costs/daily` | Bearer JWT | LLM (`model_runs.cost_usd`) + vendor (`api_costs.cost_usd`) totals per day for the last `days` days (default 30, max 365) |
| `GET` | `/admin/costs/by-agent` | Bearer JWT | Per-agent rollup of `model_runs` joined to `agent_runs` for one calendar `month=YYYY-MM` |

### SQL API (P-AD-R-sql)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/admin/sql/query` | Bearer JWT (20/min) | Read-only SELECT (or `WITH ... SELECT`) parsed via `sqlparse`; rejects any DML/DDL keyword or multi-statement payload; 30 s timeout; rows truncated at 5000 |
| `POST` | `/admin/sql/execute` | Bearer JWT (20/min) | Write SQL — requires `X-Confirm: true` and `X-Idempotency-Key` headers; statements may not reference `audit_log`, `audit_checkpoints`, or `proposals`; audit logs `execute.sql` with the statement, parameters, and idempotency key |

### Costs page (P-FE-costs)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/costs` | Bearer JWT | Costs dashboard: stacked-bar **daily** chart (LLM + vendor API) for the trailing 30 d, doughnut of **per-agent** spend for the current calendar month, and two MTD tables (by vendor across `model_runs`/`api_costs`, by agent). |
| `GET` | `/admin/costs/fragments/daily` | Bearer JWT | Daily chart fragment; ``days`` query param accepts 1..365 (selector offers 7/30/90/180/365). Returns the entire ``#costs-daily-card`` so the inline Chart.js config rehydrates on `htmx:afterSwap`. |
| `GET` | `/admin/costs/fragments/by-agent` | Bearer JWT | Doughnut fragment for the chosen ``month=YYYY-MM`` (defaults to current). Returns ``#costs-agent-card``. |
| `GET` | `/admin/costs/fragments/vendor` | Bearer JWT | MTD vendor breakdown fragment for the chosen ``month=YYYY-MM``. Returns ``#costs-vendor-card``; vendor source rendered as ``LLM`` (low-severity badge, ``model_runs``) or ``API`` (medium-severity badge, ``api_costs``). |

Charts are rendered with Chart.js (CDN, registered in `base.html`). Each
card emits its config as a sibling `<script type="application/json">` block
next to the `<canvas>`; the page-level body script destroys any existing
instance and re-initialises charts whenever an `htmx:afterSwap` reaches a
``[data-cost-chart]`` element. Tick callbacks use a `"__USD__"` sentinel
that the client replaces with a USD formatter (Chart.js options cannot be
serialised to JSON otherwise).

Data is sourced from the shared helpers extracted out of `api/costs.py`:

* `fetch_daily_costs(conn, days)` — same SQL used by `GET /admin/costs/daily`.
* `fetch_costs_by_agent(conn, month)` — same SQL used by `GET /admin/costs/by-agent`.
* `fetch_costs_by_vendor(conn, month)` — MTD union of `model_runs.provider` and `api_costs.vendor`.

No HTTP self-loops — the JSON routers and the HTML page resolve identical
SQL through the same helpers.

### Proposals page (P-FE-proposals)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/proposals` | Bearer JWT | Three-tab review page (Pending / Approved / Rejected) with a category filter. Cards render the rationale via client-side markdown-it, the `current_value`/`proposed_value` diff, `estimated_impact` metrics, evidence links (URLs and `results/...` paths link to `/admin/backtest/...`), and per-row Approve / Reject / Defer buttons. |
| `GET` | `/admin/proposals/fragments/tab` | Bearer JWT | Tab-body fragment (`status=pending\|approved\|rejected`, optional `category=` filter). Returns the cards list or the empty-state card; unknown `status` → 422. |
| `GET` | `/admin/proposals/fragments/{id}/approve-modal` | Bearer JWT | Approve modal — pre-fills `strategy_id` for `strategy_param` proposals plus a default `start_date` (1 year back) / `end_date` (today) / `universe=sp500`. |
| `POST` | `/admin/proposals/fragments/{id}/approve` | Bearer JWT (20/min) | Submits the modal; delegates to `approve_proposal_impl` (transactional UPDATE → `approved`, inserts `backtest_runs` row with `kind=validation` unless `skip_backtest=true`, writes the `approve.proposal` audit row, publishes `backtests.requested` over NATS). Returns the refreshed card (`outerHTML`) + an `HX-Trigger` flash toast. |
| `GET` | `/admin/proposals/fragments/{id}/reject-modal` | Bearer JWT | Reject modal — `review_notes` field is `required` client- and server-side (matches the `RejectProposalRequest.review_notes` `min_length=1`). |
| `POST` | `/admin/proposals/fragments/{id}/reject` | Bearer JWT (20/min) | Delegates to `reject_proposal_impl` (transactional UPDATE → `rejected`, writes `reject.proposal` audit row). Same refreshed-card + flash response shape as approve. |
| `GET` | `/admin/proposals/fragments/{id}/backtest-status` | Bearer JWT | Polled by the approved card every 5 s. Reads `backtest_runs.status` directly; terminal states (`completed`/`failed`/`cancelled`/missing) flip the `data-polling="false"` attr and detach the parent's `hx-trigger` so polling stops. |

Backed by helpers extracted from `api/proposals.py` (`fetch_proposals_page`,
`fetch_proposal_detail`, `approve_proposal_impl`, `reject_proposal_impl`,
`fetch_backtest_status`). The JSON router still owns the public REST
contract — both layers share the same SQL, transaction boundaries, and
audit/NATS side effects.

The **Defer** button is intentionally client-side only — there is no
"deferred" status in the schema. Clicking the button stores the proposal
id in `sessionStorage` under `adminProposalsDeferred` and mutes the card
visually (`opacity-60`, "deferred" badge); the state survives htmx swaps
inside the session but does not persist across sign-outs (so deferred
proposals can never silently disappear from a colleague's queue).

### SQL playground page (P-FE-sql)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/sql` | Bearer JWT | SQL playground page: CodeMirror 5 editor (CDN) with PostgreSQL syntax mode, mode radio (read-only SELECT vs write), Cmd/Ctrl+Enter shortcut, optional JSON-array parameters field, and a results pane. |
| `POST` | `/admin/sql/fragments/query` | Bearer JWT (20/min) | Runs a SELECT via `run_select_statement` and returns the result table partial (truncated at the `QUERY_MAX_ROWS` cap). Validation / postgres / timeout errors render the rose-coloured error card with HTTP 200 (kept in-pane so htmx swaps work). |
| `GET` | `/admin/sql/fragments/confirm` | Bearer JWT | Returns the "I UNDERSTAND" confirmation modal. Each request mints a fresh UUIDv7 idempotency key server-side (`_new_uuid7` — RFC 9562 §5.7 layout, 48-bit unix-ms + 74 random bits). |
| `POST` | `/admin/sql/fragments/execute` | Bearer JWT (20/min) | Server-side re-validates the typed `confirm_phrase` against `"I UNDERSTAND"`, then calls `run_write_statement` (transactional execute + `execute.sql` audit log, same SQL the JSON router uses). Success returns the emerald execute-result card plus an `HX-Trigger` flash toast; failures render the error card. |

Key client-side behaviours (`templates/sql.html`):

* CodeMirror is constructed in-place on the `<textarea#sql-statement>` element; `editor.save()` is invoked on every `htmx:configRequest` so the form submission always reflects the latest editor state.
* The form's `hx-post` defaults to `/admin/sql/fragments/query`. When the operator switches to write mode and submits, JS intercepts the submission, fetches the confirmation modal into `#modal`, and pre-fills hidden `statement` / `parameters` inputs in the modal's own form. The Run-write button stays disabled until the typed phrase matches the modal's `data-confirm-phrase`.
* CDN integrity hashes are pinned for the CodeMirror core, the PostgreSQL mode addon, and the dark / light themes.

Server-side parameter decoding (`_decode_sql_parameters`) accepts a JSON array (up to 64 values, matching the DTO cap) and returns a 422-rendered error card on malformed input — the JSON `/admin/sql/*` routes use the identical `validate_select_only` / `validate_execute` and `run_*_statement` helpers extracted from `api/sql.py`, so no HTTP self-loop.

### Violations page (P-FE-violations)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/violations` | Bearer JWT | Guard violations page — filter form (`agent_id`, `severity`, `unresolved_only` defaulted on), table with severity-coloured rows + click-to-expand JSON detail |
| `GET` | `/admin/violations/fragments/list` | Bearer JWT | Table fragment (filter + cursor pagination; `append=true` returns rows-only for "Load older") |
| `GET` | `/admin/violations/fragments/{id}/resolve-modal` | Bearer JWT | Resolve-note modal form; 404 unknown / 409 already-resolved |
| `POST` | `/admin/violations/fragments/{id}/resolve` | Bearer JWT | Resolve the violation (rate-limited 20/min) + write `resolve.guard_violation` audit log; returns refreshed row HTML and triggers a flash toast |

Backed by helpers extracted from `api/guard.py`
(`fetch_guard_violations_page`, `fetch_guard_violation`,
`resolve_guard_violation_impl`) — same SQL + transactional semantics as
the JSON router, no HTTP self-loop.

### Agents page (P-FE-agents)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/agents` | Bearer JWT | Two-pane page (left = agents list, right = detail). Content-negotiated: `Accept: text/html` returns the HTML page; anything else (e.g. `*/*`) returns the original `AgentsListResponse` JSON so the API contract stays intact. |
| `GET` | `/admin/agents/fragments/{id}/runs` | Bearer JWT | Right pane "Recent runs" tab (last 50 runs, severity-coloured status). |
| `GET` | `/admin/agents/fragments/{id}/constitution` | Bearer JWT | Right pane "Constitution" tab — emits the raw markdown inside a `<script type="text/x-markdown">` block, rendered client-side via markdown-it. JSON code blocks are highlighted with highlight.js (CDN, `github-dark` theme). |
| `GET` | `/admin/agents/fragments/{id}/run-modal` | Bearer JWT | "Run Now" modal — form with `snapshot_id`, `kind`, optional `prompt`. |
| `POST` | `/admin/agents/fragments/{id}/run` | Bearer JWT | Submits the modal form; proxies to `agent-runtime` (reusing `trigger_agent_run_impl`), writes the `run.agent` audit log, returns a flash card. Rate-limited at 20/min. |

All fragments reuse the helpers `fetch_agents_summary`,
`fetch_agent_runs`, `read_agent_constitution`, and `trigger_agent_run_impl`
extracted from `api/agents.py` — no HTTP self-loops.

### Audit page (P-FE-audit)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/audit` | Bearer JWT | Audit log page — filter form (entity_id, actor, since, limit), table, inline chain-verify form |
| `GET` | `/admin/audit/fragments/log` | Bearer JWT | Table fragment; supports `entity_id`, `actor`, `since`, `limit`, `cursor`, `append=true` (rows-only for "Load older") |
| `GET` | `/admin/audit/fragments/verify` | Bearer JWT | Runs `audit-service GET /audit/verify` for `from`/`to` query params; returns colour-coded result card (green OK, fuchsia mismatch, rose error) |

The fragment endpoints reuse `fetch_audit_log_page` and
`call_audit_service_verify` directly so the HTML and JSON surfaces share
their SQL and external-service code paths (no HTTP self-loop).

Severity colours on the audit-action badge follow the P-FE-00 palette:
`approve.*`, `submit.*`, `verify.*`, `start.backtest`, `run.agent` are
green; `reject.*`, `resolve.guard_violation` amber; `restart.service`,
`execute.sql`, `delete.*` red.

### Orders page (P-FE-orders)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/orders` | Bearer JWT | Pending orders table — instrument, side, qty, proposed price, rationale (truncated), approve/reject buttons |
| `GET` | `/admin/orders/fragments/{id}/rationale` | Bearer JWT | Expanded agent rationale (`metadata.rationale`); swap target `#rationale-{id}` |
| `GET` | `/admin/orders/fragments/{id}/rationale-snippet` | Bearer JWT | Re-renders the truncated rationale (collapse button) |
| `GET` | `/admin/orders/fragments/{id}/reject-modal` | Bearer JWT | Reject-reason modal partial; swap target `#modal` |
| `POST` | `/admin/orders/fragments/{id}/approve` | Bearer JWT (20/min) | Approves the order and returns the updated `<tr>` partial; same DB / NATS / audit-log path as `POST /admin/orders/{id}/approve` |
| `POST` | `/admin/orders/fragments/{id}/reject` | Bearer JWT (20/min) | Form-encoded `rejection_reason`; returns the updated `<tr>` partial; audit logs `reject.order` |

These routes share their business-logic helpers (`approve_pending_order`,
`reject_pending_order`) with the JSON API so there is no HTTP self-loop and
auditing / NATS publishing behaviour is identical to the JSON endpoint.

### Dashboard pages (P-FE-dashboard)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/` | Bearer JWT | Operator dashboard — 4 stat cards (pending orders, active agents, today's cost, audit chain), quick actions, Grafana iframe |
| `GET` | `/admin/fragments/stats` | Bearer JWT | htmx fragment — re-renders the 4 stat cards (polled every 30 s) |
| `POST` | `/admin/actions/verify-audit-chain` | Bearer JWT (20/min) | Proxies `audit-service GET /audit/verify` for the configured window; returns the refreshed audit card; audit logs `verify.audit_chain` |
| `POST` | `/admin/actions/run-daily-backtest` | Bearer JWT (20/min) | Proxies `backtest-engine POST /backtest/run` for `ADMIN_DAILY_BACKTEST_STRATEGY_ID`; returns a flash toast (`HX-Trigger: {"flash": ...}`); audit logs `start.backtest` |

Dashboard configuration (`.env`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `ADMIN_GRAFANA_OVERVIEW_URL` | `http://grafana:3000/d/overview?orgId=1&kiosk=tv&theme=light` | URL embedded in the dashboard `<iframe>` |
| `ADMIN_DAILY_BACKTEST_STRATEGY_ID` | *(unset — button disabled)* | Strategy slug submitted by the "Run Daily Backtest" button |
| `ADMIN_DAILY_BACKTEST_DAYS` | `30` | Rolling window length submitted with the backtest |
| `ADMIN_DAILY_BACKTEST_UNIVERSE` | *(unset)* | Optional `universe` field |
| `ADMIN_AUDIT_VERIFY_HOURS` | `24` | Lookback window used by the "Verify Audit Chain" button |

### Proposals API (P-AD-R-proposals)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/admin/proposals` | Bearer JWT | Paginated proposals (`status`, `category`, `proposed_by`, `target`, `limit`, `cursor`) |
| `GET` | `/admin/proposals/{id}` | Bearer JWT | Full proposal payload (current/proposed values, evidence, estimated impact) |
| `POST` | `/admin/proposals/{id}/approve` | Bearer JWT (20/min) | `pending` → `approved`; inserts `backtest_runs` + publishes NATS `backtests.requested` (unless `skip_backtest=true`); audit logs `approve.proposal` |
| `POST` | `/admin/proposals/{id}/reject` | Bearer JWT (20/min) | `pending` → `rejected` with required `review_notes`; audit logs `reject.proposal` |

The SQL router writes to `audit_log` from inside the same transaction as the
operator's statement, so any rollback also rolls back the audit row — the
admin connects as `tb_app`, which already lacks DELETE on the immutable
tables, but parse-time guards reject those statements with 422 before they
reach Postgres.

The restart whitelist is hard-coded to the 16 first-party services
(`admin-service`, `agent-runtime`, `api`, `audit-service`, `backtest-engine`,
`broker-adapter-alpaca`, `compliance-service`, `data-ingestion`, `guard-service`,
`llm-gateway`, `master-orchestrator`, `oms`, `risk-service`, `rnd-agent`,
`snapshot-packager`, `worker`). Infrastructure containers (Postgres, Redis,
NATS, MinIO, observability stack) are intentionally excluded.

### Additional pages

| Page | Route | Purpose |
|------|-------|---------|
| Proposals | `/proposals` | rnd-agent research proposals — approve sends to execution |
| Backtests | `/backtests` | Trigger and review backtest runs |
| Audit log | `/audit` | Read-only view of `audit_log` |
| Services | `/services` | `tb status` output, log tailing |
| Settings | `/settings` | Environment config viewer (no write) |

## Confirmation Modals

Required before every mutating action — see `.cursor/rules/frontend-htmx.mdc`:

| Action | What the modal shows |
|--------|---------------------|
| Order approve / reject | Order ID, symbol, side, quantity, price |
| Proposal approve | Proposal ID, description, estimated risk |
| Service restart | Service name, current health |
| Any SQL write | Table, operation, affected row count estimate |

## Authentication

Single-user HTTP Basic Auth backed by `ADMIN_USERNAME` + `ADMIN_PASSWORD_BCRYPT` from `.env`.
All requests require authentication. No anonymous access.

## Template Structure

```
services/admin_service/templates/
├── base.html
├── _confirm_modal.html
├── _flash.html
├── macros/ui.html
├── components/
└── pages/
```

See [.cursor/rules/frontend-htmx.mdc §Template Structure](../.cursor/rules/frontend-htmx.mdc) for the full tree.

## Performance SLO (P-AD-LOAD)

The hot read endpoint `GET /admin/orders/pending` must keep **p99 < 500 ms**
under **100 concurrent users for 60 seconds** with an error rate ≤ 1 %.

Two test harnesses enforce this:

### In-process Pytest harness

`services/admin_service/tests/test_load.py` drives the FastAPI app via the
ASGI transport against a Postgres testcontainer. It runs only when the `load`
marker is selected, so the default `make test` matrix is unaffected.

```bash
# Default profile (100 VUs / 60 s / p99 < 500 ms).
uv run --package admin-service python -m pytest \
    services/admin_service/tests/test_load.py -m load -v

# Override knobs from the environment.
ADMIN_LOAD_USERS=200 ADMIN_LOAD_DURATION_S=30 \
ADMIN_LOAD_P99_BUDGET_MS=400 \
uv run --package admin-service python -m pytest \
    services/admin_service/tests/test_load.py -m load -v -s
```

The summary line printed at the end of the run carries the requests, RPS,
p50/p95/p99, max latency, and error rate so it can be archived as a CI
artifact.

### k6 script (against a live deployment)

`scripts/load_admin_orders.js` is the same load profile but targets a real
URL (Cloudflare or Tailscale). It enforces the p99 budget via k6 thresholds
and writes `summary.json` for CI artifact collection.

```bash
# Cloudflare ingress.
k6 run \
  -e ADMIN_BASE_URL=https://admin.theeyebeta.store \
  -e ADMIN_TOKEN="$(cat ~/.theeyebeta/admin.jwt)" \
  scripts/load_admin_orders.js

# Tailscale (LAN/MagicDNS).
k6 run \
  -e ADMIN_BASE_URL=http://theeyebeta-mac:7200 \
  -e ADMIN_TOKEN="$(cat ~/.theeyebeta/admin.jwt)" \
  scripts/load_admin_orders.js
```

Pass `-e ADMIN_VUS=…`, `-e ADMIN_DURATION=…`, or `-e ADMIN_P99_BUDGET_MS=…`
to override the defaults.

## End-to-end access checklist (P-AD-LOAD)

Manual smoke before declaring a release green. Run from the Windows operator
laptop with Tailscale connected to the `theeyebeta` tailnet. Tick each item
in the PR checklist or release ticket.

### Cloudflare ingress

- [ ] `https://admin.theeyebeta.store/admin/health` returns **HTTP 200** in
      the browser (JSON `{"status":"ok",...}`); confirm the connection
      tooltip shows the Cloudflare cert chain (CN issued for
      `admin.theeyebeta.store`).
- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" https://admin.theeyebeta.store/admin/health`
      prints `200` from a non-Tailscale network (e.g. mobile hotspot).
- [ ] `Origin: https://admin.theeyebeta.store` is allowed by CORS — open
      DevTools → Network on `/admin/orders/pending` and confirm
      `Access-Control-Allow-Origin` matches the request origin.

### Tailscale ingress

- [ ] `http://theeyebeta-mac:7200/admin/health` returns **HTTP 200** in the
      browser (Tailscale MagicDNS resolves the host; admin-service binds
      `0.0.0.0`).
- [ ] `curl -sS -o /dev/null -w "%{http_code}\n" http://theeyebeta-mac:7200/admin/health`
      prints `200` from the laptop while connected to Tailscale.
- [ ] `tailscale status | grep theeyebeta-mac` shows `online` for the host.
- [ ] The same URL fails (connection refused / DNS error) when Tailscale is
      disconnected — confirms the public Tailscale ACL is not exposing 7200
      to the open internet.

### Login + JWT cookie flow

- [ ] Open `https://admin.theeyebeta.store/login`, submit the credentials
      from 1Password.
- [ ] DevTools → Application → Cookies shows
      `admin_refresh_token` set with `HttpOnly`, `Secure`, `SameSite=Lax`,
      `Path=/admin/auth`.
- [ ] DevTools → Network on the next `/admin/orders/pending` request shows
      an `Authorization: Bearer …` header (access token).
- [ ] `POST /admin/auth/refresh` (no body, cookie only) returns a fresh
      access token; the previous refresh token is revoked in Redis.
- [ ] `POST /admin/auth/logout` clears the cookie (set-cookie with `Max-Age=0`)
      and Redis no longer holds the refresh family.

### Approve a test order → audit row

- [ ] Seed a pending order:
      `psql "$ADMIN_DATABASE_URL" -f services/admin_service/tests/sql/seed_orders.sql`.
- [ ] In the Orders page, click **Approve** on the seeded order; confirm
      the modal shows order ID, symbol, side, qty, price.
- [ ] After confirming, the row transitions to `approved` and the toast
      notification appears.
- [ ] `psql "$ADMIN_DATABASE_URL" -c "SELECT actor, action, entity_id, ts
      FROM theeyebeta.audit_log WHERE action = 'approve.order'
      ORDER BY ts DESC LIMIT 1;"` shows a row whose `actor` is
      `admin-api:<your-sub>` and whose `entity_id` matches the order id.
- [ ] `nats sub 'orders.approved.>'` (separate terminal) receives a message
      with the order id.
- [ ] Final hash chain check:
      `curl -H "Authorization: Bearer $TOKEN" \
        "$ADMIN_BASE_URL/admin/audit/verify?from=$(date -u -d '-10 minutes' +%Y-%m-%dT%H:%M:%SZ)&to=$(date -u +%Y-%m-%dT%H:%M:%SZ)"`
      returns `{"ok": true, ...}`.

### Acceptance gate

The release is green when **every** checkbox above is ticked **and** the
load test (in-process or k6) reports p99 < 500 ms with error rate ≤ 1 %.

## Frontend e2e + accessibility (P-FE-FINAL)

`services/admin_service/tests/test_frontend.py` exercises the eight
server-rendered UI pages with a real Chromium instance and runs an
[axe-core](https://github.com/dequelabs/axe-core) WCAG audit on each one.

What each test asserts:

1. **Login flow works** — `POST /admin/auth/login` returns an RS256 JWT
   (`test_login_flow_works`); the gate also returns 401 when the bearer
   token is missing (`test_unauthenticated_request_is_rejected`).
2. **Page renders without console / page errors** — every `console.error`
   and uncaught `pageerror` is collected per page and asserted empty.
3. **One htmx interaction per page** triggers a real swap and the resulting
   fragment renders (dashboard refresh, orders rationale expand, audit
   filter submit, agent runs panel, violations severity filter, costs
   window change, SQL `SELECT 1`, proposals tab switch).
4. **axe-core reports 0 critical-impact violations** under the WCAG 2.0/2.1
   A + AA rule packs (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`).

### Running locally

```bash
uv sync --group dev               # installs playwright + pytest-playwright
.venv/bin/playwright install chromium
pytest services/admin_service/tests/test_frontend.py -m frontend -v
```

All tests are gated behind `@pytest.mark.frontend`; if Playwright is not
installed the module is silently skipped via `pytest.importorskip`, so CI
images without Chromium remain green. The suite spins its own uvicorn in a
background thread (free port) against the standard admin testcontainer DSN,
so no `make up` is required.

### Acceptance bar (P-FE-FINAL)

* `pytest -m frontend` exits 0 on a developer box with Chromium installed.
* axe-core reports **zero** rules with `impact === "critical"`.
* Console error sinks are empty for all eight pages.
