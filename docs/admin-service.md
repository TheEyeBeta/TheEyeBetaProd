# Admin Service

> Port 8080 — accessible over Tailscale. No public internet exposure.
> See [architecture.md §9](architecture.md#9-admin-service) and
> [.cursor/rules/frontend-htmx.mdc](../.cursor/rules/frontend-htmx.mdc).

## Stack

- **Jinja2** templates rendered server-side by FastAPI
- **htmx** for all interactive elements (no raw JavaScript)
- **Tailwind CSS** via CDN (no build step)
- **Chart.js** for data visualisation (loaded from CDN, initialised via `data-chart` attributes)

## Pages

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | System health, P&L summary, active positions |
| Market data | `/market` | Live tick feed status, feed health indicators |
| Orders | `/orders` | Order blotter, approve/reject pending orders |
| Proposals | `/proposals` | rnd-agent research proposals — approve sends to execution |
| Backtests | `/backtests` | Trigger and review backtest runs |
| Audit log | `/audit` | Read-only view of `audit_log` |
| Services | `/services` | `tb status` output, log tailing |
| Settings | `/settings` | Environment config viewer (no write) |

## Confirmation Modals

Required before every mutating action — see `.cursor/rules/frontend-htmx.mdc`:

| Action | What the modal shows |
|--------|---------------------|
| Order approve / reject | Order ID, symbol, side, quantity, price |
| Proposal approve | Proposal ID, description, estimated risk |
| Service restart | Service name, current health |
| Any SQL write | Table, operation, affected row count estimate |

## Authentication

Single-user HTTP Basic Auth backed by `ADMIN_USERNAME` + `ADMIN_PASSWORD_BCRYPT` from `.env`.
All requests require authentication. No anonymous access.

## Template Structure

```
services/admin_service/templates/
├── base.html
├── _confirm_modal.html
├── _flash.html
├── macros/ui.html
├── components/
└── pages/
```

See [.cursor/rules/frontend-htmx.mdc §Template Structure](../.cursor/rules/frontend-htmx.mdc) for the full tree.
