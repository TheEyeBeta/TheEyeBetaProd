# Connectivity

## Correct endpoints (2026-06-18)

### Tailscale (private mesh)

| Service | URL |
|---------|-----|
| Admin API | `http://the-eye-beta-server.taild51795.ts.net:7200` |
| Data API | `http://the-eye-beta-server.taild51795.ts.net:7000` |
| On-host admin | `http://127.0.0.1:7200` |
| On-host Data API | `http://127.0.0.1:7000` |

### Cloudflare Tunnel (public HTTPS)

Tunnel `my-api` (`cloudflared.service`) routes hostnames to local ports. Multiple
hostnames can share one port — the Data API listens on **7000** only.

| Public URL | Local origin | Service |
|------------|--------------|---------|
| `https://dataapiprod.theeyebeta.store` | `127.0.0.1:7000` | Data API (**prod alias**, preferred) |
| `https://dataapi.theeyebeta.store` | `127.0.0.1:7000` | Data API (legacy hostname) |
| `https://admin.theeyebeta.store` | `127.0.0.1:7200` | Admin service |
| `https://api.theeyebeta.store` | `127.0.0.1:8000` | TheEyeBetaLocal main API |

Canonical tunnel config lives in the sibling repo:
`TheEyeBetaDataAPI/deploy/cloudflared-config.yml` (install via
`sudo bash TheEyeBetaDataAPI/scripts/fix_tunnel.sh` on the server).

### Connect to the Data API tunnel

**Health check (any machine):**

```bash
curl -fsS https://dataapiprod.theeyebeta.store/health
```

**Repo smoke test:**

```bash
bash scripts/verify_dataapi_tunnel.sh
# Optional authenticated test (needs ADMIN_DATAAPI_CLIENT_ID/SECRET in .env):
bash scripts/verify_dataapi_tunnel.sh --auth
```

**Admin service** (server `.env`) — point server-side Data API calls at the tunnel
when callers are off-host, or keep loopback when admin-service runs on the same machine:

```bash
ADMIN_DATAAPI_URL=https://dataapiprod.theeyebeta.store
ADMIN_DATAAPI_CLIENT_ID=<service-client-id>
ADMIN_DATAAPI_CLIENT_SECRET=<service-client-secret>
```

**External integrations** — set base URL to `https://dataapiprod.theeyebeta.store`
and use Data API service-token auth (`POST /api/v1/auth/service-token`).

## Known DNS issue

`theeyebeta-mac` resolves to `app.nyansa.com` / `34.111.28.22` — **do not use**
for admin or Data API until Tailscale MagicDNS alias is fixed.

## Frontend configuration

Tauri `environments.ts` must use the `.ts.net` hostname until DNS is corrected.

## Bootstrap check

`scripts/bootstrap_admin.py` warns when `theeyebeta-mac` does not resolve to a
Tailscale CGNAT range (100.64.0.0/10).
