# Backend Control Plane Implementation Report

**Date:** 2026-06-16  
**Scope:** `services/admin_service` JSON/WebSocket control surface for Tauri desktop client

## What Was Added

### MASTER_ADMIN owner/operator contract
- **`GET /admin/master-admin/control-matrix`** — MASTER_ADMIN-only machine-readable control matrix. It tells the frontend what each backend feature can view/control today, which actions require confirmation/audit, and what backend/API work is still missing for full owner control.
- The matrix explicitly records gaps instead of letting the frontend pretend that trigger-only, view-only, or CLI-only features are fully controllable.

### Phase 1 — Connectivity
- **`GET /admin/login`** — browser login page (stores JWT in sessionStorage via `adminShell`)
- **CORS** — `https://tauri.localhost` added via `ADMIN_CORS_TAURI_ORIGIN`
- **`GET /admin/ops/pulse`** — real aggregation from `worker_runs`, `worker_heartbeats`, `trask_circuit_breakers`, `audit_alerts`, `orders`, `model_runs`/`api_costs`, `prelive_check_cache`, systemd timers
- **Worker APIs** — `GET /admin/workers`, `GET /admin/workers/runs`, `POST /admin/workers/{name}/run` (audited)
- **Trask APIs** — `GET /admin/trask/dashboard`, `POST /admin/trask/breakers/{id}/reset` (MASTER_ADMIN, audited)
- **Alerts APIs** — `GET /admin/alerts`, `POST /admin/alerts/{id}/ack`
- **Prelive API** — `GET /admin/prelive` (cached or `?run=true` live checks via `scripts/prelive_check.py`)

### Phase 2 — Operator Safety
- **Migration `0026_admin_rbac`** — `admin_users`, `admin_roles`, `admin_user_roles`, `prelive_check_cache`
- **RBAC** — JWT `role` claim; `require_role()` guards; env bootstrap user gets `MASTER_ADMIN`
- **SQL split** — query requires ANALYST+; execute requires MASTER_ADMIN
- **Trading** — `GET /admin/trading/live-approval/token`, `POST /admin/trading/live-approval`, `POST /admin/trading/emergency-halt`

### Phase 3 — Live Experience
- **Timers** — `GET /admin/timers`, `POST /admin/timers/{name}/trigger` (12 whitelisted units)
- **WebSocket** — `WS /admin/events/stream?token=<jwt>` with NATS bridge for normalized events

### Supporting Files
- `rbac.py`, `errors.py`, `lib/event_broadcaster.py`, `lib/queries/ops.py`, `lib/worker_registry.py`
- Pydantic DTOs in `libs/zinc_schemas/admin_dto.py`
- Tests: `test_rbac.py`, `test_control_plane.py`, `tests/sql/seed_control_plane.sql`

## Frontend Connection Guide

1. **Base URL:** `http://theeyebeta-mac:7200` (Tailscale) or Cloudflare origin
2. **Login:** `POST /admin/auth/login` with `{username, password}` → `{access_token, role, expires_in}`
3. **Requests:** `Authorization: Bearer <access_token>`; refresh via cookie on `POST /admin/auth/refresh`
4. **WebSocket:** `wss://theeyebeta-mac:7200/admin/events/stream?token=<access_token>`
5. **CORS:** Tauri origin `https://tauri.localhost` is allowed with credentials

## Endpoint Status

| Endpoint | Status |
|----------|--------|
| `/admin/login` | Functional |
| `/admin/ops/pulse` | Functional (real DB) |
| `/admin/workers*` | Functional; manual run spawns `uv run python -m workers.*` |
| `/admin/trask/*` | Functional |
| `/admin/alerts/*` | Functional |
| `/admin/prelive` | Functional (cached + live run) |
| `/admin/trading/live-approval` | Functional (needs live `accounts` rows for updates) |
| `/admin/trading/emergency-halt` | Functional (Redis + NATS; OMS undeployed) |
| `/admin/timers` | Functional where systemctl available |
| `/admin/events/stream` | Functional (NATS events when infra up) |
| `/admin/master-admin/control-matrix` | Functional (MASTER_ADMIN-only owner/operator registry) |
| Broker fills in WS | **Pending** — broker_adapter undeployed |
| OMS reconciliation UI | **Blocked** — OMS undeployed |
| MO workflow events | **Pending** — master_orchestrator undeployed |

## Remaining Blocked Items

- **OMS / broker_adapter / master_orchestrator** — order lifecycle and fill events depend on undeployed services
- **Risk/compliance panels** — empty book by design
- **Secrets / shell / sops** — intentionally CLI-only (out of scope)
- **OpenAPI JSON** — regenerate with `uv run python -c "..."` or export from running app (spec drift reduced in code; manual OpenAPI update recommended on deploy)

## Migration Required

```bash
make db-migrate   # applies 0026_admin_rbac locally
```

Seed DB users via SQL or use env `ADMIN_USERNAME`/`ADMIN_PASSWORD_BCRYPT` (bootstrap MASTER_ADMIN).
