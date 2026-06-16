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

- [ ] audit-service (+ daily chain verify timer)
- [ ] risk-service
- [ ] compliance-service
- [ ] OMS
- [ ] broker-adapter (paper credentials only)
- [ ] master-orchestrator

## Testing

- [ ] Full integration test suite green (including `test_control_plane.py`)
- [ ] 30-day paper period with zero critical incidents
- [ ] Emergency halt drill passed
- [ ] Backup restore drill passed (end of paper period)

## Operations

- [ ] Heartbeat monitor timer active (15 min)
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
