# Connectivity

## Correct endpoints (2026-06-16)

| Service | URL |
|---------|-----|
| Admin API | `http://the-eye-beta-server.taild51795.ts.net:7200` |
| Data API | `http://the-eye-beta-server.taild51795.ts.net:7000` |
| On-host | `http://127.0.0.1:7200` |

## Known DNS issue

`theeyebeta-mac` resolves to `app.nyansa.com` / `34.111.28.22` — **do not use**
for admin or Data API until Tailscale MagicDNS alias is fixed.

## Frontend configuration

Tauri `environments.ts` must use the `.ts.net` hostname until DNS is corrected.

## Bootstrap check

`scripts/bootstrap_admin.py` warns when `theeyebeta-mac` does not resolve to a
Tailscale CGNAT range (100.64.0.0/10).
