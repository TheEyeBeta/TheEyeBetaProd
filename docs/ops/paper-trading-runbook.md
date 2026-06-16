# Paper Trading Runbook

**Target go-live:** Q1 2027  
**Minimum paper period:** 30 calendar days

## Entry criteria (all required)

- [ ] All six services deployed: audit-service, risk-service, compliance-service, OMS, broker-adapter (paper), master-orchestrator
- [ ] Integration test suite green (including un-skipped `test_control_plane.py`)
- [ ] Security hardening complete: TOTP MFA, refresh reuse detection, worker/timer allowlists, SQL guards
- [ ] Observability: correlation IDs, `/metrics`, alerting rules
- [ ] Backup restore drill passed (`scripts/test_restore.sh`)

## Daily monitoring (automated)

- Zero orphan fills
- Zero silent worker deaths (15-minute heartbeat monitor)
- Zero unacknowledged CRITICAL gap alerts older than 24h
- Audit chain verify passes (daily 03:00 UTC timer)
- Reconciliation drift resolves within 5 minutes
- No broker submission without risk + compliance pass
- Emergency halt drill weekly in paper mode

## Go-live criteria (after 30-day paper)

- [ ] Zero critical incidents during paper period
- [ ] Backup restore drill repeated
- [ ] External auth/SQL/subprocess review completed
- [ ] Position and loss limits signed off
- [ ] sops secrets for all production credentials
- [ ] Tailscale ACL locked per `docs/infra/tailscale-acl-policy.json`
- [ ] `docs/ops/go-live-sign-off.md` completed
