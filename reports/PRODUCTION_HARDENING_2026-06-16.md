# Production Hardening Report — Phase 1

**Date:** 2026-06-16  
**Baseline:** Control plane v0.2.0 (commit `ba84254`, pushed to `main`)

## Completed in this session

### Process
- [x] Committed and pushed control-plane v0.2.0 (51 files)
- [x] `.gitleaks.toml` added

### Domain 1 — Security (partial)
- [x] **1.2** Refresh token reuse detection + `revoke_all_sessions` + `POST /logout/all`
- [x] **1.3** JWT RS256-only header enforcement + tests
- [x] **1.4** Worker/timer strict allowlists, subprocess list form, 300s timeout, distributed Redis locks
- [x] **1.5** SQL blocked patterns, `admin_users` protection, 1000-row cap, `SET LOCAL statement_timeout/work_mem`
- [x] **1.6** Tailscale ACL JSON + ADR-0011
- [x] **1.7** `GET/DELETE /admin/auth/sessions`
- [x] **1.1** TOTP MFA migration `0028`, enroll/verify/confirm/backup endpoints; MASTER_ADMIN enrollment gate on login

### Domain 3 — Operational reliability (partial)
- [x] **3.1** Distributed locks on worker run + timer trigger
- [x] **3.3** `ops/pulse` `asyncio.gather` with partial failure tolerance

### Domain 6 — Process (partial)
- [x] **6.4** `docs/ops/connectivity.md` + bootstrap DNS warning
- [x] Paper trading runbook, disaster recovery, alerting docs (stubs/framework)
- [x] Migration `0029_audit_worm_policy` + `audit_chain_status` table

### Other
- [x] Correlation ID middleware (`X-Request-ID`)
- [x] admin-service version bump to **0.3.0**
- [x] `pyotp` dependency

## Not completed (requires follow-up)

| Item | Blocker |
|------|---------|
| Deploy audit/risk/compliance/OMS/broker/MO services | systemd + prod credentials |
| Heartbeat monitor timer (15 min) | systemd unit not created on host |
| Audit verify timer (03:00 UTC) | systemd unit not created |
| Prometheus `/metrics` | middleware not implemented |
| OpenTelemetry order path | OMS not deployed |
| Integration tests un-skipped | testcontainers/fixture |
| `scripts/test_restore.sh` full implementation | needs backup path on host |
| OpenAPI v0.3.0 regeneration | run export after deploy |
| Rotate checklist bootstrap passwords | operator action + sops |
| Supabase sync worker fix/decommission | separate worker investigation |
| Data gap trading block in livegate | broker_adapter not deployed |
| C++ risk known-values tests | risk_service deploy |

## Migrations to apply

```bash
make db-migrate   # 0028_totp_mfa, 0029_audit_worm_policy
```

## Breaking auth change

`POST /admin/auth/login` now returns `LoginResponse` (may include `mfa_required`, `mfa_enrollment_required`) instead of always returning `access_token`. MASTER_ADMIN must enroll TOTP before receiving a full session.

## Test status

```bash
uv run pytest services/admin_service/tests/test_rbac.py \
  services/admin_service/tests/test_auth_security.py \
  services/admin_service/tests/test_layout.py -q
```

All unit tests green after hardening.
