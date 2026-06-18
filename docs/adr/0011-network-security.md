# ADR-0011: Network Security Model

**Status:** Accepted  
**Date:** 2026-06-16

## Context

TheEyeBeta admin-service (:7200) and Data API (:7000) must be reachable only by
authorized operators. Public DNS for `theeyebeta-mac` incorrectly resolves to
`app.nyansa.com` (34.111.28.22), not the Mac mini Tailscale address.

## Decision

1. **Tailscale ACL** — See `docs/infra/tailscale-acl-policy.json`. Operators
   (`tag:operator`) may reach the server (`tag:server`) on ports 7200, 7000,
   5432 (CLI Postgres only), and 22 (SSH). Server-to-server lateral movement is
   blocked.

2. **Canonical hostname** — Use `the-eye-beta-server.taild51795.ts.net` until
   MagicDNS alias `theeyebeta-mac` is corrected.

3. **Admin bind** — admin-service listens on all interfaces; edge exposure is
   controlled by Tailscale ACL + optional Cloudflare tunnel, not wide-open public
   bind.

4. **JWT auth** — All `/admin/*` JSON routes except `/admin/health` require
   RS256 Bearer tokens. Refresh tokens are httpOnly cookies with rotation and
   reuse detection.

5. **MFA** — MASTER_ADMIN requires TOTP enrollment before full session issuance.

## Consequences

- Frontend must use `.ts.net` hostname until DNS clash is fixed.
- Postgres direct access is limited to operator laptops on Tailscale.
- Compromised refresh token reuse revokes all sessions for that user.
