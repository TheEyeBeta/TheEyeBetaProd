# The Eye Terminal — Architecture Direction

> **Status:** Official direction document (Prompt 2). Describes what The Eye Terminal *is* and how the control plane must behave.  
> **Scope:** Architecture and policy only — no runtime implementation in this document.  
> **Ground truth:** Derived from the Backend + Edge Discovery Audit (2026-06-18) and live production facts.  
> **Related:** [architecture.md](architecture.md) · [admin-service.md](admin-service.md) · [api-gateway.md](api-gateway.md) · [ADR 0010](adr/0010-cloudflare-tailscale-dual-access.md) · [TheEyeBetaDataAPI TUNNEL_RUNBOOK](../../TheEyeBetaDataAPI/TheEyeBetaDataAPI/docs/TUNNEL_RUNBOOK.md)

---

## Table of Contents

1. [What The Eye Terminal Is](#1-what-the-eye-terminal-is)
2. [What It Is Not](#2-what-it-is-not)
3. [The Frontend Role](#3-the-frontend-role)
4. [The Backend / admin_service Role](#4-the-backend--admin_service-role)
5. [Internal Service Roles](#5-internal-service-roles)
6. [Worker / Timer Roles](#6-worker--timer-roles)
7. [Data API Role](#7-data-api-role)
8. [Cloudflare Role](#8-cloudflare-role)
9. [Edge Route Registry Role](#9-edge-route-registry-role)
10. [MASTER_ADMIN Role](#10-master_admin-role)
11. [Audit Role](#11-audit-role)
12. [RBAC / Security Role](#12-rbac--security-role)
13. [Dangerous-Action Model](#13-dangerous-action-model)
14. [Frontend / Backend Parity Model](#14-frontend--backend-parity-model)
15. [Deployment Model — Home Linux Server](#15-deployment-model--home-linux-server)
16. [Future Production Split Model](#16-future-production-split-model)
17. [End-to-End Request Flow](#17-end-to-end-request-flow)
18. [Control Plane Law](#18-control-plane-law)
19. [Edge Route Law](#19-edge-route-law)
20. [What MASTER_ADMIN Means](#20-what-master_admin-means)
21. [The dataapiprod :9500 Incident](#21-the-dataapiprod-9500-incident)
22. [Repository Map (As Found)](#22-repository-map-as-found)
23. [Known Gaps (Audit Baseline)](#23-known-gaps-audit-baseline)

---

## 1. What The Eye Terminal Is

**The Eye Terminal** is the operator-facing command surface for The Eye — a Bloomberg-terminal-adjacent financial operating system. It is where a trusted human operator (or a future `MASTER_ADMIN` role) observes, reasons about, and **safely controls** the full stack: market data, ingestion pipelines, agents, proposals, orders, risk, compliance, audit, workers, systemd services, and **public edge routing**.

The Terminal is **not a SaaS dashboard**. It is an **operator console** bound to a private origin (home Linux server) with a secure public edge (Cloudflare).

**Today (as found in repo):** the implemented Terminal UI lives in:

| Component | Path | Public bind |
|-----------|------|-------------|
| **admin_service** | `TheEyeProd/services/admin_service/` | `https://admin.theeyebeta.store` → `127.0.0.1:7200` |
| systemd unit | `TheEyeProd/infra/systemd/theeyebeta-admin.service` | — |

Eight HTML pages exist today: Dashboard (command center), Orders, Audit, Agents, Violations, Costs, SQL, Proposals — plus JSON APIs under `/admin/*`. See `admin_service/api/views.py` and `admin_service/web.py` (`NAV_ITEMS`).

The workspace path `TheEyeBetaAdminFrontend/` exists but is **empty** (0 files). The Terminal is implemented inside `admin_service` until a deliberate frontend split is made.

---

## 2. What It Is Not

| The Eye Terminal is **not** | Why |
|-----------------------------|-----|
| A consumer-facing fintech app | No end-user onboarding, no retail UX |
| A generic BI / Grafana replacement | Grafana is embedded read-only; Terminal owns **control** |
| Raw shell access from the browser | CLI gateway exists in Local API with allowlists; Terminal must never become arbitrary `systemctl` / bash |
| A secrets vault UI | Operators rotate and test integrations; **raw `.env`, API tokens, and Cloudflare credentials are never displayed** |
| The Data API itself | Data API (`:7000`) is a **machine-facing** service; Terminal **integrates** with it |
| Cloudflare's admin panel | Tunnel/DNS are **controlled plane facts** surfaced in Terminal via Edge Route Registry — not CF token management in UI |
| Unaudited god-mode | Every mutating action requires role, reason, confirmation where dangerous, audit log, and result |

---

## 3. The Frontend Role

The **frontend** is the **command terminal** — the only surface where operators are expected to discover capabilities, read state, and invoke allowed mutations.

**Responsibilities:**

- Render operator pages (htmx + Jinja2 today; future split to `TheEyeBetaAdminFrontend` must preserve the same control contract).
- Inject auth (JWT Bearer via `admin_service/static/js/app.js`) on every mutating request.
- Show **consequence previews** before dangerous actions (order approve, SQL execute, service restart, proposal approve, agent run).
- Reflect **control-matrix status**: visible/controllable, read-only, or backend-only with documented reason.
- Host or link the **Edge Route Registry** view at `/admin/edge` and `/admin/edge/routes` (shipped).
- **Terminal IA** — 26-module sidebar from `frontend_ia/modules.py`, validated against the control matrix; shell pages expose gaps (shipped P-FE-IA).
- Never call downstream internal services directly from the browser except through `admin_service` (or future Terminal BFF).

**Non-responsibilities:**

- Business logic for trading, risk, or compliance (delegated to engine-room services).
- Holding secrets (service client credentials, CF tokens, DB passwords).
- Arbitrary SQL or shell as the normal path.

---

## 4. The Backend / admin_service Role

**admin_service** (`TheEyeProd/services/admin_service/`, port **7200**) is the **Terminal backend** — the BFF (backend-for-frontend) and policy enforcement point for human operators.

**Responsibilities:**

| Area | Implementation (as found) |
|------|---------------------------|
| Auth | JWT RS256 (`auth.py`); single operator today (`ADMIN_USERNAME`) |
| HTML + htmx | `api/views.py`, `templates/` |
| JSON API | `api/orders.py`, `audit.py`, `agents.py`, `guard.py`, `services.py`, `backtest.py`, `costs.py`, `sql.py`, `proposals.py` |
| Downstream proxies | httpx → audit-service (`:7110`), agent-runtime (`:8004`), backtest-engine (`:7100`) |
| Direct DB reads/writes | asyncpg via `deps.py` → `theeyebeta.*` tables |
| NATS publishes | Order approve, proposal backtest trigger |
| systemd (whitelisted) | `api/services.py` — status + restart for named units only |
| Audit writes | `audit_log.py` → `theeyebeta.audit_log` on mutations |

**Route namespace:** all operator routes under `/admin/*`. Public health: `GET /admin/health`.

**OpenAPI artifact:** `docs/api/admin.openapi.json`.

admin_service does **not** replace internal microservices. It **orchestrates visibility and safe control** over them.

---

## 5. Internal Service Roles

Internal services run on loopback (or Docker/Caddy mTLS internally). They form the **engine room**. Source: `TheEyeProd/services/`, `docker-compose.yml`, `infra/caddy/Caddyfile`.

| Service | Port (default) | Role | Terminal exposure today |
|---------|----------------|------|-------------------------|
| **data-ingestion** | 7010 | Canonical price/macro ingest triggers | Missing |
| **snapshot-packager** | 7011 | Build packaged snapshots | Missing |
| **llm-gateway** | 4000 / 7020 | LiteLLM proxy | Costs rollup only |
| **agent-runtime** | 8004 | Run agents on demand | Partial (Agents page) |
| **guard-service** | 7040 gRPC / 8005 HTTP | Agent output validation | Partial (violations via DB) |
| **master-orchestrator** | 7050 | Workflow orchestration (`market-trio`) | Missing |
| **risk-service** | 7060 gRPC / 8007 HTTP | Order validation, portfolio metrics | Missing |
| **compliance-service** | 7070 gRPC / 8008 HTTP | Order compliance checks | Missing |
| **oms** | 7080 (`settings.py`; Makefile stale `:8009`) | Order state, reconciliation, submission gate | Partial (Orders via DB) |
| **broker-adapter-alpaca** | 7090 | Alpaca paper/live adapter | Missing |
| **backtest-engine** | 7100 | Backtest runs | Partial (API + dashboard action) |
| **audit-service** | 7110 | Hash-chain verify, NATS consumer, WORM export | Partial (verify proxy) |
| **rnd-agent** | 7120 | Nightly R&D proposals | Partial (Proposals page) |

**Security note (audit finding):** most internal HTTP/gRPC services have **no application-level auth** today; isolation relies on loopback bind + Caddy mTLS (`*.theeyebeta.internal`). Terminal must proxy through admin_service with RBAC — never expose these ports via Cloudflare directly.

**Local stack** (`TheEyeBetaLocal/`, sibling repo):

| Service | Port | Role |
|---------|------|------|
| Main API | 8000 | Terminal UI routes, Trask dashboard API, CLI gateway, Finnhub proxy |
| Trask health | 8090 | Trask monitoring health server |
| Engine | — | Background engine process (`theeyebeta-engine.service`) |

Public: `https://api.theeyebeta.store` → `127.0.0.1:8000` per `TheEyeBetaDataAPI/deploy/cloudflared-config.yml`.

---

## 6. Worker / Timer Roles

Workers are **scheduled and batch processors** — not interactive Terminal pages, but **first-class control-plane citizens**. They must appear in the Terminal (status, last run, manual trigger where safe).

**TheEyeProd workers** (`TheEyeProd/workers/`) + **systemd timers** (`TheEyeProd/deploy/systemd/`):

| Timer / unit | Schedule (UTC) | Worker / command |
|--------------|----------------|------------------|
| `theeye-gap-sentinel.timer` | Mon–Fri 07:30 | `gap_sentinel_worker` |
| `theeye-macro.timer` | Mon–Fri 21:20 | `macro_pipeline` |
| `theeye-massive-ingest.timer` | Mon–Fri 21:30 | massive + indicator + sector workers |
| `theeye-daily-pipeline.timer` | Mon–Fri 21:35 | mirror + `daily_pipeline_runner` |
| `theeye-sector.timer` | Mon–Fri 22:05 | `sector_aggregation_worker` |
| `theeye-supabase-sync.timer` | Mon–Fri 22:20 | `supabase_sync_worker --shadow` |
| `theeye-intraday-ingest.timer` | Mon–Fri */15 min | `intraday_ingestion_worker` |
| `theeye-backup.timer` | Daily 02:00 | `scripts/backup_db.sh` |

**TheEyeBetaLocal timers:** `theeyebeta-daily.timer` (Mon–Fri 18:00) → `theeyebeta-daily.service`.

Workers inherit audit/heartbeat patterns from `workers/base_worker.py`. Terminal exposure: **missing** (audit baseline).

---

## 7. Data API Role

**TheEyeBetaDataAPI** (`TheEyeBetaDataAPI/TheEyeBetaDataAPI/`) is the **external machine API** — scoped JWT auth, market/advisor/portfolio/admin-read routes, Prometheus metrics.

| Fact | Value |
|------|-------|
| Bind | `127.0.0.1:7000` (`app/core/config.py`, `API_PORT=7000`) |
| systemd | `theeyebeta-dataapi.service` — **generated** by `scripts/install_service.sh` (not committed) |
| Health | `GET /health` → `{ status, database, redis? }` (`app/api/routes/health.py`) |
| Trusted hosts | `TRUSTED_HOSTS` env → `TrustedHostMiddleware` (`app/main.py`) |
| Admin read routes | `/api/v1/admin/*` — requires `admin:read` scope (`app/api/routes/admin.py`) |
| Dev test UI | `TheEyeBetaDataAPI/frontend/public/index.html` (not integrated into Terminal) |

**Route modules (18 files):** `health`, `auth`, `context`, `chat`, `data`, `market_data`, `symbols`, `analytics`, `signals`, `portfolio`, `reference`, `tickers`, `financials`, `indicators`, `macro`, `news`, `admin`.

**Not in repo but documented:** `trades.py`, `internal.py` referenced in `docs/api-gateway.md` — treat as planned migration, not deployed routes.

Data API is **not** the operator Terminal. Operators reach Data API **through** Terminal integration (health, ETL status, engine status, worker heartbeats) and through Edge Route Registry — not by browsing `/docs` on `:7000` as primary ops.

---

## 8. Cloudflare Role

Cloudflare is the **secure public edge** — not deployment trivia. It terminates TLS, applies WAF/Access policy, and forwards to the private origin via **Cloudflare Tunnel** (`cloudflared`).

**Canonical tunnel config (committed):**

`TheEyeBetaDataAPI/TheEyeBetaDataAPI/deploy/cloudflared-config.yml`

```yaml
ingress:
  - hostname: api.theeyebeta.store
    service: http://127.0.0.1:8000
  - hostname: dataapi.theeyebeta.store
    service: http://127.0.0.1:7000
  - hostname: admin.theeyebeta.store
    service: http://127.0.0.1:7200
  - service: http_status:404
```

**Operational scripts:**

| Script | Repo | Purpose |
|--------|------|---------|
| `scripts/fix_tunnel.sh` | TheEyeBetaDataAPI | Copy canonical config → `/etc/cloudflared/config.yml`, restart `cloudflared` |
| `scripts/sync_tunnel.sh` | TheEyeBetaDataAPI | DNS + remote ingress sync |
| `infra/cloudflared/apply-p-net-01.sh` | TheEyeProd | Insert `admin.theeyebeta.store` block into host config |

**Host config:** `/etc/cloudflared/config.yml` — **not in git**; drift source. See [§21](#21-the-dataapiprod-9500-incident).

**Dual access (ADR 0010):** Tailscale for operator mesh (SSH, internal metrics); Cloudflare Tunnel for public HTTPS (`admin`, `api`, `dataapi` hostnames).

**Optional future layer:** Cloudflare Worker / API Gateway in front of Tunnel for rate limits, geo rules, or request shaping — not required today but reserved in the flow diagram below.

---

## 9. Edge Route Registry Role

The **Edge Route Registry** is a **production control-plane module** (shipped in `admin_service/edge/`). It is the authoritative inventory reconciling:

- public hostname
- Cloudflare tunnel route (local + remote ingress if available)
- internal target host + port
- owning service + systemd unit
- application trusted-host allowlist entry
- health endpoint + expected response
- runtime config vs repo config
- **drift status**

**Why it exists:** the [dataapiprod :9500 incident](#21-the-dataapiprod-9500-incident) proved that tunnel and trusted-host misconfiguration causes production outages invisible to the operator Terminal.

**Target ownership:** `admin_service` exposes read API + Terminal UI; canonical rows seeded from `deploy/cloudflared-config.yml`, `.env.example` TRUSTED_HOSTS, systemd unit maps, and periodic health/drift probes.

**Safety:** registry displays hostnames and ports — never raw secrets, CF API tokens, or full `.env` values.

---

## 10. MASTER_ADMIN Role

`MASTER_ADMIN` is the **highest operator role** in the Terminal RBAC model (**planned** — not implemented; today any valid JWT is equivalent).

See [§20 — What MASTER_ADMIN Means](#20-what-master_admin-means) for the full definition.

**Implementation direction:**

- JWT claim or parallel role table (e.g. `roles: ["MASTER_ADMIN"]`).
- Required for: service restart, SQL execute, order approve, live-trading gates, tunnel-adjacent actions, secret **rotation workflows** (not raw secret view).
- Distinct from service principals (`admin-tool` client in Data API `SERVICE_CLIENTS_JSON`) and DB roles (`tb_app`, `tb_rnd_readonly`).

---

## 11. Audit Role

Audit is **append-only truth** for operator and system actions.

**Storage (TheEyeProd):**

| Object | Migration | Purpose |
|--------|-----------|---------|
| `theeyebeta.audit_log` | `db/migrations/versions/0009_audit.py` | Partitioned hash chain (`prev_hash`, `row_hash`) |
| `theeyebeta.audit_checkpoints` | `0014_audit_checkpoints.py` | WORM export metadata |
| `audit_service` | `services/audit_service/` | Verify chain, NATS consumer, MinIO export |

**admin_service writes:** `audit_log.py` — used by orders, proposals, SQL execute, service restart, agents, guard, backtest.

**Terminal:** Audit page (`/admin/audit`) + dashboard verify action → proxies `audit-service` `GET /audit/verify`.

Audit is **not optional** for dangerous actions. Missing audit = control-plane bug.

---

## 12. RBAC / Security Role

**Layers (defense in depth):**

| Layer | Mechanism | As found |
|-------|-----------|----------|
| Edge | Cloudflare Access (admin), WAF | ADR 0010; not fully verifiable from repo |
| Transport | TLS at CF edge; Tunnel to loopback | `cloudflared-config.yml` |
| Terminal auth | JWT RS256, refresh cookie | `admin_service/auth.py` |
| RBAC | Per-route role checks | **Missing** — single user |
| Data API auth | Service token + scoped Bearer JWT | `app/auth/scopes.py` |
| Network | Loopback bind + Caddy mTLS internal | `infra/caddy/Caddyfile` |
| DB | Role separation `tb_app` / `tb_rnd_readonly` | Migrations `0015` |
| Rate limit | slowapi on admin; Data API middleware | 100/min default, 20/min mutating |

**Non-negotiable rules (Terminal policy):**

- Never expose raw secrets, CF tokens, or `.env` in UI/API responses.
- Never arbitrary shell or arbitrary `systemctl` from frontend.
- Never arbitrary SQL as the normal operating path (`sql.py` — SELECT on `/query`; writes on `/execute` with confirmation + protected tables).
- Mutations require role check, reason, confirmation (if dangerous), audit log, success/failure result.

---

## 13. Dangerous-Action Model

Every mutating capability is classified:

| Class | Requirements | Examples (as found) |
|-------|--------------|---------------------|
| **Safe read** | Auth optional or JWT | Dashboard stats, audit log list |
| **Privileged read** | JWT + scope/role | SQL SELECT, named Data API queries |
| **Reversible mutate** | JWT + reason + audit | Guard violation resolve |
| **Dangerous mutate** | JWT + **MASTER_ADMIN** (future) + confirmation + consequence preview + audit | Order approve, proposal approve, agent run, backtest run |
| **Critical infrastructure** | MASTER_ADMIN + confirmation + audit + registry update | Service restart (`api/services.py`), tunnel config (CLI today — must move to guarded Terminal workflow) |
| **Forbidden from UI** | Backend-only or CLI with sudo | Raw `fix_tunnel.sh`, undifferentiated shell |

**Existing dangerous paths without full Terminal coverage:**

- `broker_adapter_alpaca` `POST /v1/orders/market` — no HTTP auth
- `oms/submission_gate.py` pause/resume — no Terminal UI
- `TheEyeBetaLocal/.../trask.py` worker control POSTs — no auth
- `data_ingestion` `POST /ingest/run` — Basic auth only, no Terminal

---

## 14. Frontend / Backend Parity Model

**Core law:** every backend capability must map to exactly one control-matrix state (see [§18](#18-control-plane-law)).

| State | Meaning | Terminal obligation |
|-------|---------|---------------------|
| **Controllable** | Operator can invoke safe mutation | Page + API + audit + RBAC |
| **Read-only visible** | Operator can inspect | Page or dashboard panel |
| **Backend-only (documented)** | Intentionally not in UI | Listed in registry with **reason** (e.g. NATS consumer, hash-chain writer) |
| **Missing** | No mapping | **Bug** — implement or document |

**Parity workflow (build order):**

1. Register capability in control matrix / Edge Route Registry.
2. Expose read path in Terminal.
3. Add mutation with dangerous-action model if applicable.
4. Add tests (`admin_service/tests/` pattern).
5. Update this document and `admin-service.md`.

**Current parity score (audit):** ~8 modules with UI vs 25+ backend modules — significant gaps in Edge, Data API, Risk, Compliance, Broker, Workers, Emergency trading.

---

## 15. Deployment Model — Home Linux Server

**Production host:** Mac mini (M2 Pro, 32 GB RAM) running Linux — see `architecture.md` §2.

**Process model (native, not Docker for public apps):**

| Public hostname | Port | systemd unit | Install path |
|-----------------|------|--------------|--------------|
| `admin.theeyebeta.store` | 7200 | `theeyebeta-admin.service` | `TheEyeProd/infra/systemd/` |
| `dataapi.theeyebeta.store` | 7000 | `theeyebeta-dataapi.service` | Generated: `DataAPI/scripts/install_service.sh` |
| `api.theeyebeta.store` | 8000 | `theeyebeta-api.service` | `TheEyeBetaLocal/scripts/systemd/` |
| Tunnel | — | `cloudflared.service` | Host + `fix_tunnel.sh` |

**Engine room:** Docker Compose on same host for Postgres, Redis, NATS, MinIO, observability, and selected services (`TheEyeProd/docker-compose.yml`).

**Deploy flow:** Git pull on server → `make deploy` / service-specific restart → health verify. CI via Tailscale SSH (ADR 0010). Emergency reference: `docs/headless-operations.md`.

**Watchdog:** `TheEyeBetaDataAPI/scripts/watchdog_all.sh` — tmux session checks `:7000`, `:8000`, and public health URLs.

---

## 16. Future Production Split Model

**Current fact:** `dataapi.theeyebeta.store` and `dataapiprod.theeyebeta.store` both route to the **same** backend (`127.0.0.1:7000`, same Data API process and database). Production health (verified 2026-06):

```bash
curl https://dataapiprod.theeyebeta.store/health
# {"status":"healthy","database":true,"redis":null}

curl https://dataapi.theeyebeta.store/health
# {"status":"healthy","database":true,"redis":null}
```

**This is valid only if intentional** (e.g. alternate DNS alias, CF Access split, or legacy hostname). The codebase **does not register** `dataapiprod.theeyebeta.store` in `deploy/cloudflared-config.yml` or `.env.example` TRUSTED_HOSTS — it is production-only configuration.

**When staging/prod separation is required**, split along these boundaries — never share a port by accident:

| Dimension | Split candidate |
|-----------|-----------------|
| Hostname | `dataapi.*` vs `dataapiprod.*` |
| Tunnel ingress | Separate `service:` lines |
| Port | e.g. `:7000` staging vs `:7001` prod (explicit) |
| Process | Separate systemd units |
| Config | Separate `.env`, `TRUSTED_HOSTS`, `DATABASE_URL` |
| Database | Separate Postgres database or cluster |
| Terminal | Edge Route Registry shows both rows with drift checks |

Until split: Registry must record both hostnames pointing at `:7000` with explicit **"shared backend — intentional"** flag.

---

## 17. End-to-End Request Flow

```txt
User / MASTER_ADMIN
        |
        v
Cloudflare DNS / WAF / Access
        |
        v
Optional Cloudflare Worker / API Gateway
        |
        v
Cloudflare Tunnel (cloudflared.service)
        |
        v
Home Linux Server (127.0.0.1)
        |
        +-- admin.theeyebeta.store   -> :7200 -> admin_service (/admin/*)
        +-- dataapi.theeyebeta.store -> :7000 -> Data API (/health, /api/v1/*)
        +-- dataapiprod.theeyebeta.store -> :7000 -> Data API (same backend today)
        +-- api.theeyebeta.store     -> :8000 -> TheEyeBetaLocal Main API
        |
        v
Internal services (loopback / Caddy mTLS)
        |
        v
Postgres/Timescale, Redis, NATS, MinIO, broker, agents, workers
```

**Data API edge paths (required facts):**

```txt
dataapi.theeyebeta.store      -> Cloudflare Tunnel -> 127.0.0.1:7000 -> Data API -> GET /health
dataapiprod.theeyebeta.store  -> Cloudflare Tunnel -> 127.0.0.1:7000 -> Data API -> GET /health
```

**Operator Terminal path:**

```txt
MASTER_ADMIN -> https://admin.theeyebeta.store/admin/ -> admin_service:7200
              -> DB / NATS / httpx proxies -> internal services
              -> (future) Edge Route Registry -> health + drift probes -> Data API :7000 / tunnel config
```

---

## 18. Control Plane Law

Every backend capability must be exactly one of:

1. **Visible and controllable** from the Terminal (with RBAC, audit, and dangerous-action rules), or
2. **Visible and read-only** from the Terminal, or
3. **Visible and backend-only** with an explicit documented reason in the control matrix.

**Otherwise it is missing or broken.**

Examples of **backend-only with reason** (acceptable if documented):

- NATS JetStream audit consumer (`audit_service/consumer.py`) — no direct UI; Terminal shows verify + log tail.
- Broker WebSocket fill streamer — event-driven; Terminal shows positions/orders snapshot.
- `cloudflared` process — controlled via Registry + guarded ops workflow, not raw config editor.

Examples of **broken (audit baseline):**

- Edge routes — no Registry, no Terminal page.
- OMS submission gate — no visibility.
- Worker timers — no last-run status in Terminal.
- Data API admin routes — exist at `:7000` but not integrated into `:7200` Terminal.

---

## 19. Edge Route Law

Every **public hostname** must have a registered row containing at minimum:

| Field | Source of truth (priority order) |
|-------|----------------------------------|
| Public hostname | DNS / Cloudflare dashboard |
| Cloudflare tunnel route | `deploy/cloudflared-config.yml` → host `/etc/cloudflared/config.yml` → remote ingress API |
| Internal target host | Always `127.0.0.1` today |
| Internal target port | Service settings / systemd |
| Service owner | Repo + service name |
| systemd unit | `infra/systemd/` or generated install scripts |
| Health endpoint | e.g. `/health`, `/admin/health` |
| Expected health response | e.g. `{"status":"healthy","database":true,...}` |
| Trusted host required | yes/no — Data API: **yes** (`TRUSTED_HOSTS`) |
| Trusted host present | runtime `.env` names only — never raw values in Registry |
| Drift status | `ok` / `port_mismatch` / `host_header_risk` / `unknown` |

**Port 9500 is not a registered route.** Any tunnel target not in the Registry is **incident-class drift**.

**Registered routes (canonical repo):**

| Hostname | Port | Service | Unit | Health |
|----------|------|---------|------|--------|
| `dataapi.theeyebeta.store` | 7000 | TheEyeBetaDataAPI | `theeyebeta-dataapi` | `/health` |
| `dataapiprod.theeyebeta.store` | 7000 | TheEyeBetaDataAPI (shared) | `theeyebeta-dataapi` | `/health` |
| `api.theeyebeta.store` | 8000 | TheEyeBetaLocal Main API | `theeyebeta-api` | `/health` |
| `admin.theeyebeta.store` | 7200 | admin_service | `theeyebeta-admin` | `/admin/health` |

---

## 20. What MASTER_ADMIN Means

**MASTER_ADMIN** is the designated human operator role with:

| Granted | Description |
|---------|-------------|
| **Full visibility** | All Terminal pages, Registry, audit, worker status, edge health |
| **Full ownership** | Accountability for production mutations and incident response |
| **Safe control of dangerous systems** | Orders, proposals, SQL writes, service restarts, trading gates — with confirmation + audit |
| **Secret/integration lifecycle** | Rotate, test, disable integrations **without seeing raw secret values** in UI |

**MASTER_ADMIN does not mean:**

| Forbidden | Reason |
|-----------|--------|
| Raw secret exposure | `.env`, CF tokens, client secrets stay in SOPS/host env |
| Arbitrary shell | No unbounded CLI/subprocess from browser |
| Reckless unaudited control | Every mutation logs to `audit_log` with actor, reason, payload |
| Bypassing Edge Route Law | Tunnel changes go through Registry + guarded workflow |

Today the codebase implements **single-user JWT** without role claims (`auth.py`). Implementing MASTER_ADMIN is a **required** Terminal milestone before expanding dangerous-action surface.

---

## 21. The dataapiprod :9500 Incident

**This incident is the canonical reason the Edge Route Registry must exist.**

### Timeline (production facts)

1. Cloudflare Tunnel routed **`dataapiprod.theeyebeta.store`** to **`127.0.0.1:9500`**.
2. **Nothing was listening on port 9500** (Data API runs on **7000** per `config.py`, `server.sh`, `theeyebeta-dataapi.service` install script).
3. Cloudflare returned **`502`** to clients.
4. After correcting the tunnel route to **`127.0.0.1:7000`**, the API returned **`400 Invalid host header`** — FastAPI `TrustedHostMiddleware` rejected the Host header.
5. **`dataapiprod.theeyebeta.store`** had to be added to runtime **`TRUSTED_HOSTS`** (not present in committed `.env.example`, which lists only `api.theeyebeta.store,dataapi.theeyebeta.store,...`).
6. After restarting **`theeyebeta-dataapi.service`**, both hostnames returned healthy responses from `GET /health`.

### Root causes (systemic)

| Cause | Gap |
|-------|-----|
| Tunnel port drift (`9500` vs `7000`) | No Registry; no Terminal visibility; `:9500` never registered in repo |
| Host header rejection | TRUSTED_HOSTS not tied to Registry; `dataapiprod` not in example config |
| Dual config sources | `cloudflared-config.yml`, `/etc/cloudflared/config.yml`, `sync_tunnel.sh` remote ingress — no reconciliation |
| Hostname absent from repo | Zero grep matches for `dataapiprod` in `TheEyeBeta2025` |

### Required outcomes (architecture, not yet implemented)

- Registry row for every public hostname including `dataapiprod`.
- Drift detector: tunnel port ≠ registered port → alert in Terminal.
- TRUSTED_HOSTS parity check: hostname in tunnel but not in allowlist → `host_header_risk`.
- Smoke tests must curl **both** Data API hostnames (today `fix_tunnel.sh` documents only `dataapi.theeyebeta.store`).

---

## 22. Repository Map (As Found)

| Repo / path | Role in Terminal architecture |
|-------------|-------------------------------|
| `TheEyeProd/services/admin_service/` | **The Eye Terminal** (UI + BFF) |
| `TheEyeProd/services/*` | Engine-room microservices |
| `TheEyeProd/workers/` + `deploy/systemd/` | Scheduled ingestion and pipelines |
| `TheEyeProd/infra/systemd/theeyebeta-admin.service` | Terminal systemd unit |
| `TheEyeProd/infra/cloudflared/apply-p-net-01.sh` | Admin hostname tunnel helper |
| `TheEyeBetaDataAPI/TheEyeBetaDataAPI/` | Data API `:7000` |
| `TheEyeBetaDataAPI/.../deploy/cloudflared-config.yml` | Canonical tunnel ingress |
| `TheEyeBetaDataAPI/.../scripts/fix_tunnel.sh` | Tunnel install/repair |
| `TheEyeBetaLocal/` | Main API `:8000`, engine, Trask |
| `TheEyeBetaAdminFrontend/` | **Empty** — reserved name; no code yet |

---

## 23. Known Gaps (Audit Baseline)

Track implementation against this list:

- [x] Edge Route Registry module (`/admin/edge`, `edge/service.py`) — drift probes; live CF API optional
- [x] Cloudflare/Edge status page (`/admin/cloudflare/status`, `/admin/edge`)
- [ ] `dataapiprod.theeyebeta.store` in canonical config + `.env.example` + smoke scripts
- [ ] RBAC + MASTER_ADMIN role claims
- [ ] `/admin/login` template
- [ ] Services page (systemd matrix beyond 4 units)
- [ ] Data API admin integration into Terminal
- [ ] Emergency trading / OMS submission gate UI
- [ ] Worker/timer status panel
- [ ] Risk, compliance, broker read-only panels
- [ ] Fix doc drift (`api-gateway.md` trades routes; `admin-service.md` Basic vs JWT)
- [ ] Trask missing route modules (`trask/api/routes/`)

---

*Last updated: 2026-06-18 — Backend + Edge Discovery Audit baseline.*
