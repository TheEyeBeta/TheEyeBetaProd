# API Gateway — Route Catalog and Non-Overlap

> **P-AG-01** — Preserve existing `:7000` routes; document separation from `admin-service` on `:7200`.
> This document is **read-only** with respect to application code: no route changes are implied here.

---

## 1. Summary

| Gateway | Port | Bind | Path namespace | Status in `TheEyeProd` |
|---------|------|------|----------------|-------------------------|
| **main-api** | **7000** | `127.0.0.1` | `/`, `/health`, `/api/v1/*` | **`services/main_api/` not scaffolded** — production routes today live in sibling repo [`TheEyeBetaDataAPI`](../../TheEyeBetaDataAPI/TheEyeBetaDataAPI/) (`app/main.py`, `app/api/routes/*`). Placeholder: `services/api/` (empty `pyproject.toml` only). |
| **admin-service** | **7200** (target) | `0.0.0.0` / Tailscale | **`/admin/*`** | **`services/admin_service/` not scaffolded** — routes specified in [`admin-service.md`](admin-service.md) and [`.cursor/rules/frontend-htmx.mdc`](../.cursor/rules/frontend-htmx.mdc). Legacy docs reference port **8080**; P-AG-01 assigns **7200** with `/admin` prefix. |

**Non-overlap verdict:** No route on main-api (`:7000`) shares the `/admin/*` URL prefix owned by admin-service (`:7200`). No ADR rename is required (see [§5](#5-overlap-analysis)).

---

## 2. Audit method

1. Searched `services/main_api/` and `services/main_api/routes/` — **not present** in this monorepo.
2. Attempted live `GET http://127.0.0.1:7000/openapi.json` — **service not running** on the audit host.
3. Static audit of **TheEyeBetaDataAPI** (`app/api/routes/*.py`, `app/main.py`) — the deployed FastAPI app that binds to **port 7000** today.
4. Admin routes taken from **planned** `admin-service` specs (htmx + page table), normalized to `/admin/*` per P-AG-01.

When `services/main_api/` is migrated into this repo, re-run:

```bash
curl -s http://127.0.0.1:7000/openapi.json | jq '.paths | keys'
```

and update the tables in §3.

---

## 3. Main API (`:7000`) — full route catalog

**Application:** TheEyeBetaDataAPI (to become `services/main_api/`).  
**Framework:** FastAPI.  
**OpenAPI:** `/docs`, `/openapi.json` (standard FastAPI).

### 3.1 Authentication model

| Mechanism | Used on | Notes |
|-----------|---------|-------|
| None | `GET /health`, `GET /` | Public probes |
| HTTP Basic (client id + secret) | `POST /api/v1/auth/service-token` | Issues scoped bearer JWT |
| Bearer JWT | All other `/api/v1/*` | Scopes enforced per route; optional mTLS headers (`X-Service-Client-Id`, `X-Client-Cert-Subject`) when `SERVICE_MTLS_ENABLED` |
| User JWT | Same bearer path | OIDC/JWKS or symmetric `USER_JWT_SECRET` |

**Scope constants** (`app/auth/scopes.py`): `market:read`, `symbols:read`, `analytics:read`, `advisor:read`, `signals:read`, `portfolio:read`, `trades:read`, `trades:write`, `admin:read`, `admin:write`, `admin:*`, `internal:jobs`.

### 3.2 Routes

| Method | Path | Auth | Purpose | Typical caller |
|--------|------|------|---------|----------------|
| `GET` | `/` | None | API name/version stub | Load balancers, humans |
| `GET` | `/health` | None | API + DB health | Cloudflare tunnel, `verify_remote_access.sh`, monitoring |
| `POST` | `/api/v1/auth/service-token` | HTTP Basic (service client) | Exchange client credentials for scoped JWT | VI app, Iris backend, internal automation |
| `GET` | `/api/v1/context` | Bearer · `advisor:read` | Advisor context payload (alias) | ChatGPT app / Iris (`dataapi` client) |
| `GET` | `/api/v1/advisor/context` | Bearer · `advisor:read` | Same as above (canonical advisor path) | External AI clients |
| `POST` | `/api/v1/chat` | Bearer · `advisor:read` | DB-grounded chat (alias) | Iris / advisor frontends |
| `POST` | `/api/v1/advisor/chat` | Bearer · `advisor:read` | Same as above (canonical) | External AI clients |
| `GET` | `/api/v1/market-data/quotes` | Bearer · `market:read` | Latest quotes for comma-separated symbols | Trading UI, agents |
| `GET` | `/api/v1/symbols/search` | Bearer · `symbols:read` | Symbol lookup | Autocomplete, research tools |
| `GET` | `/api/v1/analytics/snapshots/{ticker}` | Bearer · `analytics:read` | Precomputed analytics snapshot for one ticker | Advisor context builders |
| `GET` | `/api/v1/signals/latest` | Bearer · `signals:read` | Latest signals (optional ticker filter) | Signal consumers, dashboards |
| `GET` | `/api/v1/portfolio/state` | Bearer · `portfolio:read` | Ownership-aware positions/state; users limited to self | Portfolio widgets, service principals with `owner_subject` |
| `POST` | `/api/v1/trades/orders` | Bearer · `trades:write` + **`Idempotency-Key`** header | Place order with idempotency + audit trail | Automated trading / OMS bridge (external) |
| `GET` | `/api/v1/admin/audit-events` | Bearer · `admin:read` | Read orchestration audit events (DB-backed, API shape) | Privileged service clients — **not** the htmx admin UI |
| `POST` | `/api/v1/internal/jobs/rebuild-indicators` | Bearer · `internal:jobs` | Enqueue indicator rebuild job | Internal batch / ops automation |

**Rate limiting:** `RateLimitMiddleware` (optional Redis backend).  
**CORS:** Configured allowlist; methods `GET`, `POST`, `OPTIONS`.

### 3.3 Source map (pre-migration)

| Route group | Source file |
|-------------|-------------|
| Health | `TheEyeBetaDataAPI/app/api/routes/health.py` |
| Auth | `TheEyeBetaDataAPI/app/api/routes/auth.py` |
| Advisor context | `TheEyeBetaDataAPI/app/api/routes/context.py` |
| Advisor chat | `TheEyeBetaDataAPI/app/api/routes/chat.py` |
| Market data | `TheEyeBetaDataAPI/app/api/routes/market_data.py` |
| Symbols | `TheEyeBetaDataAPI/app/api/routes/symbols.py` |
| Analytics | `TheEyeBetaDataAPI/app/api/routes/analytics.py` |
| Signals | `TheEyeBetaDataAPI/app/api/routes/signals.py` |
| Portfolio | `TheEyeBetaDataAPI/app/api/routes/portfolio.py` |
| Trades | `TheEyeBetaDataAPI/app/api/routes/trades.py` |
| API admin read | `TheEyeBetaDataAPI/app/api/routes/admin.py` |
| Internal jobs | `TheEyeBetaDataAPI/app/api/routes/internal.py` |
| App factory | `TheEyeBetaDataAPI/app/main.py` |

---

## 4. Admin service (`:7200`) — planned `/admin/*` catalog

**Application:** `admin-service` (htmx + Jinja2).  
**Auth:** DB-backed JWT/RBAC with MFA for `MASTER_ADMIN`; no env bootstrap admin
fallback ([`admin-service.md`](admin-service.md)).

Page routes from [`admin-service.md`](admin-service.md), normalized to the **P-AG-01 `/admin` prefix**:

| Method | Path | Auth | Purpose | Caller |
|--------|------|------|---------|--------|
| `GET` | `/admin/` | HTTP Basic | Dashboard — health, P&L summary, positions | Operator browser (Tailscale / Cloudflare Access) |
| `GET` | `/admin/market` | HTTP Basic | Live tick feed status | Operator |
| `GET` | `/admin/orders` | HTTP Basic | Order blotter (pending + history) | Operator |
| `GET` | `/admin/proposals` | HTTP Basic | rnd-agent proposals queue | Operator |
| `GET` | `/admin/backtests` | HTTP Basic | Trigger/review backtest runs | Operator |
| `GET` | `/admin/audit` | HTTP Basic | Read-only `audit_log` viewer (sanitized) | Operator |
| `GET` | `/admin/services` | HTTP Basic | `tb status`, log tail fragments | Operator |
| `GET` | `/admin/settings` | HTTP Basic | Read-only env/config viewer | Operator |

**htmx fragment / mutation routes** (from [`.cursor/rules/frontend-htmx.mdc`](../.cursor/rules/frontend-htmx.mdc)):

| Method | Path | Auth | Purpose | Caller |
|--------|------|------|---------|--------|
| `GET` | `/admin/status/feeds` | HTTP Basic | Poll feed health partial | htmx `every 5s` |
| `GET` | `/admin/orders` | HTTP Basic | Paginated order rows (`?page=`) | htmx infinite scroll |
| `GET` | `/admin/orders/{order_id}/confirm-approve` | HTTP Basic | Approval confirmation modal HTML | htmx modal |
| `POST` | `/admin/orders/{order_id}/approve` | HTTP Basic + CSRF | Approve pending order → OMS | Operator |
| `POST` | `/admin/orders/{order_id}/reject` | HTTP Basic + CSRF | Reject pending order (planned; same pattern as approve) | Operator |
| `DELETE` | `/admin/cache/{key}` | HTTP Basic + CSRF | Evict Redis/cache key | Operator |
| `POST` | `/admin/proposals/{id}/approve` | HTTP Basic + CSRF | Send proposal to execution (planned) | Operator |
| `POST` | `/admin/services/{svc}/restart` | HTTP Basic + CSRF | `tb restart` wrapper (planned) | Operator |

FastAPI also exposes `/docs` and `/health` on admin-service if implemented like other services; those paths are **not** under `/admin/*` and are listed separately in service READMEs when added.

---

## 5. Overlap analysis

### 5.1 Path-prefix rule (P-AG-01 acceptance criterion)

Admin-service **owns** the first path segment `/admin` on port **7200**.

Main-api on port **7000** exposes:

- `/` and `/health` at the root
- Versioned JSON under `/api/v1/...`
- One admin-related **API** subtree: `/api/v1/admin/audit-events` (scope `admin:read`)

**No main-api route starts with `/admin/`** (the UI prefix). Therefore there is **no URL collision** on the same host:port between the two services, and **no rename ADR** is required.

### 5.2 Semantic overlaps (intentional, different surfaces)

These features sound similar but are **different routes, ports, and auth models**:

| Concern | Main API (`:7000`) | Admin UI (`:7200`) |
|---------|-------------------|-------------------|
| Audit trail | `GET /api/v1/admin/audit-events` — JSON, bearer `admin:read` | `GET /admin/audit` — HTML over `audit_log` / summary view |
| Orders | `POST /api/v1/trades/orders` — programmatic place | `GET/POST /admin/orders/*` — human approve/reject |
| Health | `GET /health` — JSON probe | `GET /admin/` dashboard + `GET /admin/status/feeds` partial |

Operators and automation must not confuse **`/api/v1/admin/*`** (machine API on 7000) with **`/admin/*`** (human UI on 7200).

### 5.3 Port separation

| Port | Service | Exposure |
|------|---------|----------|
| 7000 | main-api (Data API) | Loopback; Cloudflare tunnel to `dataapiprod.theeyebeta.store` and `dataapi.theeyebeta.store` (see [connectivity.md](ops/connectivity.md)) |
| 7200 | admin-service | Tailscale / Cloudflare Access (see [ADR 0010](adr/0010-cloudflare-tailscale-dual-access.md)) |

Different ports alone prevent accidental routing overlap even if paths were ever aliased at a reverse proxy.

---

## 6. Related internal services (not part of this gateway doc)

These FastAPI apps use **other ports** and **must not** be folded into main-api or admin route tables:

| Port | Service | Example paths |
|------|---------|---------------|
| 8001–8009, 7090–7110 | theeyebeta execution/research stack | `/health`, `/v1/validate-order`, `/oms/orders/{id}/approve`, … |
| 8080 (legacy doc) | admin-service alternate port in [`architecture.md`](architecture.md) | Superseded by **7200** for P-AG-01 |

See [`architecture.md` §2.2](architecture.md#22-port-map) for the full port map.

---

## 7. Maintenance

- **When `services/main_api/` lands:** copy §3 tables from OpenAPI or `routes/`, delete the TheEyeBetaDataAPI cross-reference, and add a row to [`architecture.md` §2.2](architecture.md#22-port-map) for port 7000.
- **When `services/admin_service/` lands:** confirm implemented paths match §4; update port in `architecture.md` from 8080 → 7200 if not already done.
- **If a future route must use `/admin` on port 7000:** open `docs/adr/0011-main-api-route-rename.md` before merging (not needed today).

---

## 8. References

- [`TheEyeBetaDataAPI/README.md`](../../TheEyeBetaDataAPI/TheEyeBetaDataAPI/README.md) — capability list and curl examples
- [`docs/admin-service.md`](admin-service.md) — admin UI pages and auth
- [`docs/architecture.md`](architecture.md) — production topology
- [`docs/adr/0009-htmx-admin-frontend.md`](adr/0009-htmx-admin-frontend.md) — why admin is SSR/htmx
