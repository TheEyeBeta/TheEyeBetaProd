# ADR 0010: Cloudflare Tunnel + Tailscale for Dual-Mode Remote Access

**Status:** Accepted — 2026-05-21
**Deciders:** Platform team
**Related:** [docs/architecture.md §12](../architecture.md#12-deployment), [ADR 0009](0009-htmx-admin-frontend.md)

---

## Context

The production Mac mini sits on a home network with a dynamic IP address and no open inbound ports. The admin dashboard (Part 7.8) and Grafana (Part 7.9) must be accessible from:

1. **Operator devices** (laptop, phone) anywhere in the world — low latency, always-on.
2. **GitHub Actions CI/CD runner** — the deploy workflow must SSH to the Mac mini without a public IP or port-forwarding rule.
3. **Future: external webhook receivers** — Alpaca broker callbacks, Stripe billing, etc.

Requirements:
- No port-forwarding or dynamic DNS.
- No static IP required.
- Traffic to the admin UI must be authenticated.
- SSH for deployment must not expose port 22 to the public internet.

---

## Decision

We use **two complementary access layers**:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Operator mesh** | Tailscale (WireGuard mesh VPN) | SSH, Grafana, Prometheus, NATS monitor — all internal tooling |
| **Public HTTPS** | Cloudflare Tunnel (`cloudflared`) | Admin service HTTP (with Cloudflare Access auth), future webhooks |

**Tailscale** connects operator devices and the CI runner into a private WireGuard mesh. All services bound to `127.0.0.1` are reachable at the Mac mini's Tailscale IP without any inbound port. The deploy workflow authenticates via Tailscale OAuth.

**Cloudflare Tunnel** creates an outbound-only encrypted tunnel from the Mac mini to Cloudflare's edge. The admin service at `:8080` is exposed at `https://admin.theeyebeta.example.com` with Cloudflare Access (email OTP or GitHub OAuth) as the authentication gate. No inbound port is opened on the router.

---

## Consequences

### Positive
- **Zero router configuration.** Both tunnels are outbound-only. No NAT punch-through, no dynamic DNS, no ISP restrictions.
- **Layered auth.** Tailscale provides device-level authentication (certificate-based WireGuard). Cloudflare Access provides user-level authentication (email OTP/GitHub SSO) in front of the admin UI.
- **Operator ergonomics.** Tailscale MagicDNS gives stable hostnames (`theeyebeta-mac`) regardless of IP changes. `ssh theeyebeta-mac` works from any device in the tailnet.
- **Cloudflare edge caching.** Static assets for the admin UI (Tailwind CDN, Chart.js) are cached at Cloudflare's edge — not served from the Mac mini.
- **Independent failure modes.** If Cloudflare has an outage, Tailscale (and therefore SSH + ops) continues to work. If Tailscale has an outage, the admin UI via Cloudflare still works.

### Negative
- **Two access systems to maintain.** Tailscale and Cloudflare have separate auth configurations, access policies, and billing.
- **`cloudflared` daemon** must run on the Mac mini and be kept running (systemd/launchd service). A crashed `cloudflared` silently drops public access until restarted.
- **Cloudflare Access rate limits.** Free tier limits to 50 seats; sufficient for now.
- **Latency via Cloudflare.** Requests to the admin UI traverse Cloudflare's edge before reaching the Mac mini. Measured additional latency: ~20–40 ms depending on PoP. Acceptable for an ops dashboard.

### Neutral
- MinIO console (`:9001`) and Grafana (`:3000`) are Tailscale-only. They do not need public access and carry sensitive data.
- All services still bind to `127.0.0.1`; Cloudflare Tunnel reaches them via `localhost` on the Mac mini, not via a public port.
- Webhook receiver services (future) will be exposed via Cloudflare Tunnel with path-based routing (`/webhooks/alpaca`, `/webhooks/stripe`).

---

## Alternatives Considered

| Option | Why rejected |
|--------|-------------|
| **Dynamic DNS + port forwarding** | Requires router access; exposes services to the public internet; no auth layer |
| **Tailscale only** | No easy HTTPS public endpoint for webhooks; requires Tailscale client on every device (including mobile); less convenient for sharing a read-only dashboard link |
| **Cloudflare Tunnel only** | No WireGuard mesh; SSH would need to go through Cloudflare, adding latency and a provider dependency to the deploy critical path |
| **Wireguard (self-hosted)** | Requires a public VPS for the WireGuard server endpoint; adds infrastructure to maintain; Tailscale adds key distribution and device management on top |
| **ngrok** | Session-based tunnels (not persistent); paid plan for custom domain; less security control than Cloudflare Access |
| **AWS/GCP bastion** | Cloud cost; VPC setup; no benefit over Tailscale for a single-host deployment |

---

## References

- [Tailscale documentation](https://tailscale.com/kb/)
- [Cloudflare Tunnel documentation](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Cloudflare Access documentation](https://developers.cloudflare.com/cloudflare-one/policies/access/)
- [docs/architecture.md §12](../architecture.md#12-deployment)
- [ADR 0009 — htmx admin frontend](0009-htmx-admin-frontend.md)
