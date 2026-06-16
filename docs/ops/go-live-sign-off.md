# Go-Live Sign-Off Checklist

**Target:** Q1 2027 live trading  
**Paper period minimum:** 30 calendar days

## Security

- [ ] TOTP MFA enrolled for all MASTER_ADMIN accounts
- [ ] Bootstrap checklist passwords rotated via sops
- [ ] JWT keys in sops-managed secrets (not ad-hoc PEM paths)
- [ ] Tailscale ACL applied per `docs/infra/tailscale-acl-policy.json`
- [ ] gitleaks scan clean on `main`

## Services deployed (paper mode)

- [x] audit-service (+ daily chain verify timer) — active on :7110; JetStream consumer connected
- [x] broker-adapter (paper credentials only) — `theeye-broker-adapter-alpaca.service` on :7090
- [x] risk-service — active :8007/:7060
- [x] compliance-service — active :8008/:7070
- [ ] OMS — blocked until `make build-cpp` (needs `zinc_native._zinc_oms`)
- [x] master-orchestrator — active :7050

## Testing

- [ ] Full integration test suite green (including `test_control_plane.py`)
- [ ] 30-day paper period with zero critical incidents
- [ ] Emergency halt drill passed
- [ ] Backup restore drill passed (end of paper period)

## Operations

- [x] Heartbeat monitor timer active (15 min)
- [x] Migration head at `0030_audit_chain_status`
- [x] All prelive checks pass (2026-06-16 activation run)
- [x] No stale heartbeats (IndicatorComputeWorker refreshed 2026-06-16)
- [x] Audit-service active; `theeye-audit-verify` timer enabled (04:00 UTC)
- [ ] Prometheus `/metrics` scraped
- [ ] Alerting rules configured (Telegram/email)
- [ ] `docs/ops/paper-trading-runbook.md` criteria met

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Operator | | | |
| Risk | | | |
| Compliance | | | |
| MASTER_ADMIN | | | |
