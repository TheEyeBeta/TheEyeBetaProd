# Tailscale database access — full setup guide

Connect a **client computer** (laptop, desktop) to the production PostgreSQL database on
the Mac mini (`the-eye-beta-server`). **All data stays on the server** — the client only
sends SQL over Tailscale; nothing is stored or synced locally.

| Item | Value |
|------|-------|
| Server hostname | `the-eye-beta-server` (Tailscale MagicDNS) |
| Server Tailscale IP | `100.77.87.18` (may change — prefer MagicDNS) |
| Port | `5432` |
| Database | `TheEyeBeta2025Live` |
| Read/write user | `tb_app` |
| Read-mostly user | `tb_rnd_readonly` |
| Superuser (server only) | `postgres` — migrations/admin, **never** on laptop |
| Primary schema | `theeyebeta` |

**Quick links**

| Audience | Jump to |
|----------|---------|
| Human — Mac mini setup | [Part 1](#part-1--human-setup-mac-mini-server) |
| Human — laptop setup | [Part 2](#part-2--human-setup-your-computer) |
| Understanding passwords | [Credentials explained](#credentials-explained) |
| AI agent | [Part 3](#part-3--ai-agent-setup) |

---

## How it works

```
Your computer                    Mac mini (the-eye-beta-server)
┌─────────────────┐             ┌──────────────────────────────┐
│ Tailscale       │  WireGuard  │ Tailscale (snap, autostart)  │
│ .env.laptop     │ ──────────► │ PostgreSQL 16 (:5432)        │
│ psql / DBeaver  │   tailnet   │ TheEyeBeta2025Live           │
│ Cursor / scripts│             │ all rows live here only      │
└─────────────────┘             └──────────────────────────────┘
```

Three layers must all be correct:

1. **Tailscale** — both machines on the same tailnet
2. **Network** — Postgres accepts connections from `100.64.0.0/10` (`pg_hba.conf`)
3. **Credentials** — `tb_app` password in Postgres matches `TB_APP_PASSWORD` in your env files

---

## Credentials explained

This is the part that causes the most confusion. There are **three PostgreSQL users** and
**two env files** (server vs laptop).

### PostgreSQL roles

| Role | Purpose | Use from laptop? |
|------|---------|------------------|
| `postgres` | Superuser — migrations, admin, `ALTER ROLE` | **No** — server localhost only |
| **`tb_app`** | **Normal read/write** on `theeyebeta.*` | **Yes** — this is what you use |
| `tb_rnd_readonly` | Read-mostly + limited proposal writes | Optional |

`tb_app` permissions:

| Allowed | Blocked |
|---------|---------|
| `SELECT` / `INSERT` / `UPDATE` / `DELETE` on most `theeyebeta.*` tables | `postgres` superuser over Tailscale |
| `INSERT` + `SELECT` on `theeyebeta.audit_log` | `UPDATE` / `DELETE` on `audit_log` (append-only) |

### What is `TB_APP_PASSWORD`?

`TB_APP_PASSWORD` is the **login password for the PostgreSQL user `tb_app`**. It is:

- **Not** a Tailscale password
- **Not** the `postgres` superuser password
- **Not** stored in git — only in `.env` (server) and `.env.laptop` (your computer)

Think of it as: **username = `tb_app`, password = value of `TB_APP_PASSWORD`**.

### Server `.env` keys (Mac mini only)

| Variable | What it is | Example host |
|----------|------------|--------------|
| `DATABASE_URL` | Superuser URL for migrations/admin (`postgres` role) | `127.0.0.1` |
| `TB_APP_PASSWORD` | Password for the `tb_app` role — **source of truth** | n/a |
| `TB_RND_PASSWORD` | Password for `tb_rnd_readonly` | n/a |
| `INGEST_DATABASE_URL` | Full URL using `tb_app` — **must match `TB_APP_PASSWORD`** | `127.0.0.1` on server |

```env
# Server .env (Mac mini) — structure, not real secrets
DATABASE_URL=postgresql+psycopg://postgres:<postgres-pw>@127.0.0.1:5432/TheEyeBeta2025Live
TB_APP_PASSWORD=<your-tb_app-password>
TB_RND_PASSWORD=<your-tb_rnd-password>
INGEST_DATABASE_URL=postgresql://tb_app:<same-as-TB_APP_PASSWORD>@127.0.0.1:5432/TheEyeBeta2025Live
```

### Laptop `.env.laptop` (your computer)

Only needs the connection profile — no superuser URL:

```env
THEEYEBETA_DB_HOST=the-eye-beta-server
THEEYEBETA_DB_PORT=5432
THEEYEBETA_DB_NAME=TheEyeBeta2025Live
THEEYEBETA_DB_USER=tb_app
TB_APP_PASSWORD=<same value as server .env TB_APP_PASSWORD>
```

`make laptop-db-env` builds `DATABASE_URL` and `INGEST_DATABASE_URL` pointing at
`the-eye-beta-server` (not `localhost`).

### The #1 mistake: password out of sync

Postgres stores the password **inside the database** (`ALTER ROLE tb_app PASSWORD '...'`).
Your `.env` files store a **copy** for apps to use. Both must match.

| Symptom | Cause |
|---------|-------|
| `password authentication failed for user "tb_app"` | `.env` password ≠ Postgres role password |
| Works with old password, not new one | You changed `TB_APP_PASSWORD` in `.env` but didn't `ALTER ROLE` |
| `INGEST_DATABASE_URL` fails but `TB_APP_PASSWORD` works | URL still has old password embedded |

**Fix on the Mac mini** (run as `postgres` superuser):

```bash
# Load server .env, then sync Postgres to match
set -a && source .env && set +a
url="${DATABASE_URL/postgresql+psycopg/postgresql}"
psql "$url" -c "ALTER ROLE tb_app PASSWORD '${TB_APP_PASSWORD}';"
psql "$url" -c "ALTER ROLE tb_rnd_readonly PASSWORD '${TB_RND_PASSWORD}';"
```

Then confirm `INGEST_DATABASE_URL` uses the same password as `TB_APP_PASSWORD` (not a
stale `tb_app_CHANGE_ME` placeholder).

---

## Part 1 — Human setup: Mac mini (server)

Run these on the Mac mini. When complete, `make tailscale-db-status` reports **SERVER READY**.

### 1.1 Tailscale

Tailscale is installed via **snap** and autostarts:

```bash
tailscale status          # should show the-eye-beta-server online
tailscale ip -4           # e.g. 100.77.87.18
snap services tailscale   # tailscale.tailscaled should be enabled + active
```

Sign in with your Tailscale account. The machine hostname is **`the-eye-beta-server`**.

### 1.2 PostgreSQL (already configured)

Production Postgres runs **natively** on the host (not Docker):

| Setting | Value |
|---------|-------|
| Version | PostgreSQL 16 |
| `listen_addresses` | `*` (all interfaces) |
| `pg_hba` Tailscale rule | `host all all 100.64.0.0/10 scram-sha-256` |
| Config path | `/etc/postgresql/16/main/` |

Verify:

```bash
ss -tln | grep 5432          # LISTEN on 0.0.0.0:5432
make tailscale-db-status
```

### 1.3 Server `.env` — set and sync passwords

1. Ensure `.env` exists in the repo root on the Mac mini.
2. Set `TB_APP_PASSWORD` to your chosen password.
3. Set `INGEST_DATABASE_URL` so the password in the URL **equals** `TB_APP_PASSWORD`:

```env
TB_APP_PASSWORD=your-chosen-password
INGEST_DATABASE_URL=postgresql://tb_app:your-chosen-password@127.0.0.1:5432/TheEyeBeta2025Live
```

4. Sync Postgres roles (see [password sync](#the-1-mistake-password-out-of-sync) above).

### 1.4 Verify server end-to-end

```bash
cd /path/to/theeyebeta
make tailscale-db-status
```

All server checks should pass:

- Tailscale online
- Postgres listening
- `pg_hba` allows `100.64.0.0/10`
- `tb_app` read + write via Tailscale IP
- MagicDNS hostname resolves

The script will warn **"no other tailnet peers"** until your laptop joins — that is expected.

---

## Part 2 — Human setup: your computer

### Prerequisites

| Tool | macOS | Linux | Windows |
|------|-------|-------|---------|
| Tailscale | [Download](https://tailscale.com/download) | Same | Same |
| `psql` | `brew install libpq` | `apt install postgresql-client` | WSL or pg installer |
| Repo clone | `git clone …` | Same | Same |

### Step 1 — Join the tailnet

1. Install Tailscale on your computer.
2. Sign in with the **same account** as the Mac mini.
3. Verify:

```bash
tailscale status    # must list the-eye-beta-server as a peer
```

### Step 2 — Clone repo and create `.env.laptop`

```bash
git clone <your-repo-url> theeyebeta
cd theeyebeta
make laptop-db-setup
```

Edit `.env.laptop` — set `TB_APP_PASSWORD` to the **exact same value** as on the server:

```env
TB_APP_PASSWORD=<copy from server .env TB_APP_PASSWORD line>
```

### Step 3 — Verify read/write from your computer

```bash
make laptop-db-check
```

Expected: **`All checks passed`**.

### Step 4 — Use the database

```bash
make laptop-db-psql                    # interactive terminal
eval "$(make laptop-db-env)"           # export DATABASE_URL for scripts
```

**GUI client (TablePlus, DBeaver, pgAdmin, DataGrip):**

| Field | Value |
|-------|-------|
| Host | `the-eye-beta-server` |
| Port | `5432` |
| Database | `TheEyeBeta2025Live` |
| Username | `tb_app` |
| Password | value of `TB_APP_PASSWORD` in `.env.laptop` |
| SSL | Off (Tailscale encrypts the tunnel) |

---

## Troubleshooting (human)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Tailscale not connected` | Not signed in on laptop | Open Tailscale → Connect |
| `peer 'the-eye-beta-server' not listed` | Wrong account or server off | Same Tailscale account; power on Mac mini |
| `cannot reach …:5432` | Server down or ACL blocks port | `make tailscale-db-status` on server |
| `password authentication failed` | Password mismatch | Sync Postgres + `.env` + `.env.laptop` (see above) |
| `psql: command not found` | Client not installed | Install `postgresql-client` / `libpq` |
| Short hostname fails on server only | `/etc/hosts` maps `the-eye-beta-server` → `127.0.1.1` locally | Use MagicDNS FQDN or `100.x` IP on server; laptop is unaffected |

**Tailscale admin:** https://login.tailscale.com/admin

---

## Part 3 — AI agent setup

> **Audience:** Cursor, Claude Code, or any automation agent. Follow literally.

### Mission

1. **Server (Mac mini):** Postgres + Tailscale + `tb_app` password synced; verification green.
2. **Client (laptop):** `.env.laptop` with matching `TB_APP_PASSWORD`; `make laptop-db-check` exits 0.

Data stays on the server. No local Postgres. No Docker for the database on the client.

### Hard constraints

1. **Never** commit `.env`, `.env.laptop`, or passwords.
2. **Never** use `postgres` superuser from a client over Tailscale — use `tb_app`.
3. **Never** `UPDATE` / `DELETE` on `theeyebeta.audit_log` or `public.score_audit_log`.
4. **Never** run destructive SQL without explicit user approval.
5. Client host is **`the-eye-beta-server`**, not `localhost` / `postgres` (Docker).
6. `TB_APP_PASSWORD` in env files must match `ALTER ROLE tb_app` in Postgres.

### Architecture

```yaml
data_location: Mac mini only (the-eye-beta-server)
transport: Tailscale WireGuard (100.64.0.0/10)
postgres: native PG 16, TCP 5432, listen_addresses: "*"
pg_hba_tailscale: "host all all 100.64.0.0/10 scram-sha-256"
tailscale_service: snap tailscale.tailscaled (enabled, active)
roles:
  postgres: superuser, server localhost only
  tb_app: read/write app role, used from laptop
  tb_rnd_readonly: read-mostly
database: TheEyeBeta2025Live
schema: theeyebeta
```

### Repository files

| Path | Machine | Purpose |
|------|---------|---------|
| `.env` | Server | `DATABASE_URL`, `TB_APP_PASSWORD`, `INGEST_DATABASE_URL` |
| `.env.laptop` | Client | `TB_APP_PASSWORD`, host `the-eye-beta-server` |
| `.env.laptop.example` | Repo | Committed template |
| `scripts/verify_tailscale_db.sh` | Server | Server-only checks |
| `scripts/tailscale_e2e_status.sh` | Server | Server + peer checklist |
| `scripts/laptop_db.sh` | Client | `check` / `psql` / `env` |
| `Makefile` | Both | `tailscale-db-status`, `laptop-db-*` |

### Server procedure (Mac mini)

```bash
cd <repo-root>

# 1. Tailscale
tailscale status | grep -F the-eye-beta-server
snap services tailscale | grep active

# 2. Verify Postgres + pg_hba + tb_app over Tailscale IP
make tailscale-db-status
# EXPECT: all server checks OK

# 3. If tb_app auth fails — sync password
set -a && source .env && set +a
url="${DATABASE_URL/postgresql+psycopg/postgresql}"
psql "$url" -c "ALTER ROLE tb_app PASSWORD '${TB_APP_PASSWORD}';"
psql "$url" -c "ALTER ROLE tb_rnd_readonly PASSWORD '${TB_RND_PASSWORD}';"

# 4. Confirm INGEST_DATABASE_URL password matches TB_APP_PASSWORD
grep -E '^TB_APP_PASSWORD=|^INGEST_DATABASE_URL=' .env
# EXPECT: same password in both

# 5. Re-verify
make tailscale-db-status
```

### Client procedure (laptop)

```bash
tailscale status | grep -F the-eye-beta-server
cd <repo-root>
make laptop-db-setup
# User sets TB_APP_PASSWORD in .env.laptop = server .env value
make laptop-db-check
# EXPECT: exit 0
eval "$(make laptop-db-env)"
# EXPECT: DATABASE_URL host = the-eye-beta-server
```

### Connection strings (client, after `make laptop-db-env`)

```yaml
DATABASE_URL: "postgresql+psycopg://tb_app:<pw>@the-eye-beta-server:5432/TheEyeBeta2025Live"
INGEST_DATABASE_URL: "postgresql://tb_app:<pw>@the-eye-beta-server:5432/TheEyeBeta2025Live"
POSTGRES_SCHEMA: theeyebeta
```

### Success criteria

```yaml
server:
  make tailscale-db-status: server checks pass
  tb_app via 100.x Tailscale IP: read + write OK
client:
  make laptop-db-check: exit 0
  DATABASE_URL host: the-eye-beta-server
  no local postgres required
```

### Failure matrix

| Failure | Fix |
|---------|-----|
| `password authentication failed` | `ALTER ROLE tb_app` on server; sync `.env` + `.env.laptop` + `INGEST_DATABASE_URL` |
| TCP 5432 unreachable | Server `make tailscale-db-status`; Tailscale ACLs |
| No peer listed | Laptop `tailscale up`, same account |
| `INGEST_DATABASE_URL` stale | Replace embedded password with current `TB_APP_PASSWORD` |

### Related docs

- [`docs/headless-operations.md`](headless-operations.md) — ops runbook
- [`docs/adr/0010-cloudflare-tailscale-dual-access.md`](adr/0010-cloudflare-tailscale-dual-access.md) — network architecture
- [`.cursor/rules/db-engineer.mdc`](../.cursor/rules/db-engineer.mdc) — SQL safety rules
