# theeyebeta — Headless Operations

> **One-stop emergency reference.** Bookmark this page. Works on a phone.
> Full architecture detail lives in [architecture.md](architecture.md).
> Build an SSH alias: `alias teb='ssh <user>@theeyebeta-mac'`.

---

## ⚡ Cheat Sheet

```
HEALTH          tb status
LOGS            tb logs <svc>            make logs-<svc>
RESTART         tb restart <svc>         (confirms before acting)
DEPLOY ONE      tb deploy <svc>          (pull + restart, confirms)
DEPLOY ALL      tb deploy --all          (rolling, confirms)
STOP TRADING    docker compose stop agent-runtime broker-adapter-alpaca oms
START INFRA     make up                  docker compose up -d --wait
STOP ALL        make down
SSH TO BOX      ssh <user>@theeyebeta-mac
DB SHELL        tb db shell
MIGRATE         tb db migrate --prod     (dry-run first, confirms)
ROLLBACK        git reset --hard <sha> && docker compose up -d --force-recreate
SECRET EDIT     tb secrets edit dev
FULL RESTART    make down && make up
```

**Service ports (all on 127.0.0.1 unless noted):**

| Port | Service | Port | Service |
|------|---------|------|---------|
| 8001 | data-ingestion | 7090 | broker-adapter-alpaca |
| 8002 | snapshot-packager | 7100 | backtest-engine |
| 8003 | llm-gateway | 7110 | audit-service |
| 8004 | agent-runtime | 7120 | rnd-agent |
| 8005 | guard-service | **7200** | **admin-service** (0.0.0.0) |
| 8006 | master-orchestrator | 5432 | PostgreSQL |
| 8007 | risk-service | 6379 | Redis |
| 8008 | compliance-service | 4222 | NATS |
| 8009 | oms | **3000** | **Grafana** (Tailscale) |

---

## 🚨 Everything Is Broken

**Do this in order. Do not skip steps.**

### Step 0 — Stop live trading first

```bash
docker compose stop agent-runtime broker-adapter-alpaca oms
```

Then breathe, then diagnose.

### Step 1 — Can you reach the box?

```bash
ssh <user>@theeyebeta-mac            # if on Tailscale
ping theeyebeta-mac                  # Tailscale DNS
```

- **No response:** check [Tailscale admin](#-consoles--contacts) → is the node online?  
  If the machine is physically unreachable, restart it at the data centre.
- **SSH works:** continue to Step 2.

### Step 2 — What is running?

```bash
docker compose ps                    # all containers + health status
tb status                            # service-level health summary
```

### Step 3 — Find the error

```bash
tb logs <svc>                        # last 100 lines + follow
docker compose logs --tail=200 <svc> # raw Docker logs
journalctl -u docker -n 100          # Docker daemon errors
```

**Common failures and fixes:**

| Symptom | First check | Quick fix |
|---------|-------------|-----------|
| Service in restart loop | `tb logs <svc>` — missing env var? | `tb secrets decrypt dev` + `tb restart <svc>` |
| Postgres connection refused | `docker compose ps postgres` — healthy? | `docker compose restart postgres` |
| NATS not accepting connections | `curl -s http://localhost:8222/healthz` | `docker compose restart nats` |
| Redis NOAUTH / WRONGPASS | `.env` REDIS_PASSWORD mismatch | re-decrypt secrets, restart redis |
| LLM calls failing 429 | [Anthropic console](#-consoles--contacts) — check quota | reduce agent concurrency or wait |
| Alpaca orders rejected | [Alpaca dashboard](#-consoles--contacts) — check account status | pause broker-adapter-alpaca |
| OMS submission paused | Redis key `oms:submissions:paused` set | `POST /oms/reconciliation/resolve` |
| Disk full | `df -h` | clear old Docker images: `docker image prune -f` |

### Step 4 — Rollback if needed

```bash
ssh <user>@theeyebeta-mac
cd ~/theeyebeta
git log --oneline -10               # find the last good commit hash
git reset --hard <sha>
docker compose pull
docker compose up -d --force-recreate
sleep 30 && tb status
```

### Step 5 — Resume trading

```bash
docker compose start oms broker-adapter-alpaca agent-runtime
tb status
```

---

## 📞 Consoles & Contacts

| Service | URL | What you need there |
|---------|-----|-------------------|
| Anthropic | https://console.anthropic.com | API key rotation, usage/quota |
| OpenAI | https://platform.openai.com | API key rotation, usage/quota |
| Alpaca | https://app.alpaca.markets | Account status, paper/live toggle, orders |
| Cloudflare | https://dash.cloudflare.com | DNS, tunnel health, WAF rules for `/admin` |
| Tailscale | https://login.tailscale.com/admin | Machine connectivity, ACLs, SSH keys |
| Grafana | http://theeyebeta-mac:3000 | Dashboards, alerts (Tailscale required) |
| GitHub Actions | https://github.com/<org>/theeyebeta/actions | CI/deploy status |
| MinIO | http://theeyebeta-mac:9001 | Snapshot blobs, storage (Tailscale required) |

**Emergency contacts:**

| Role | Name | Contact |
|------|------|---------|
| System owner | [YOUR NAME] | [YOUR PHONE / SIGNAL] |
| Backup contact | [BACKUP NAME] | [BACKUP PHONE] |

---

## `tb` CLI Reference

```
tb status                    Service health summary (green / yellow / red)
tb logs <svc>                Tail service logs
tb restart <svc>             Restart a service — prompts for confirmation
tb deploy <svc>              Pull latest image + restart — prompts for confirmation
tb deploy --all              Rolling deploy of all services — prompts for confirmation

tb backtest run <config>     Submit a backtest job
tb backtest status <id>      Check backtest job status
tb backtest results <id>     Download results

tb db migrate                Run alembic upgrade head (LOCAL only)
tb db migrate --prod         Migrate production — dry-run offered, then confirms
tb db shell                  Open psql on production DB

tb secrets decrypt <env>     Decrypt secrets/dev.enc.yaml → .env
tb secrets edit <env>        Open sops editor for a secrets file
```

---

## Common Tasks

### Deploy after a hotfix (automated path)

```bash
git commit -m "fix(oms): ..."
git push origin main
# deploy.yml triggers automatically; monitor at GitHub Actions URL above
```

### Manual single-service restart

```bash
tb restart oms               # prompts: "Restart oms on production? [y/N]"
```

### Apply a schema migration

```bash
tb db migrate --prod --dry-run    # ALWAYS review first
tb db migrate --prod              # shows plan, requires "yes"
```

### Run a backtest

```bash
tb backtest run services/backtest-engine/configs/sp500_momentum.yaml
tb backtest status <job-id>
```

### Rotate an API key

```bash
tb secrets edit dev               # opens sops editor
# Change the key value, save and exit
tb restart llm-gateway            # (or whichever service uses the key)
```

### Check the audit chain

```bash
curl -s "http://localhost:7110/audit/verify?from=2026-01-01T00:00:00Z&to=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Expect: {"status":"OK","rows_checked":N,...}
```

### Tail all services at once

```bash
docker compose logs -f --tail=50 2>&1 | grep -v healthcheck
```

---

## Deploy Runbook

**Normal path** — push to `main`, `deploy.yml` handles everything.

**Emergency manual deploy:**

```bash
ssh <user>@theeyebeta-mac
cd ~/theeyebeta
git fetch origin && git reset --hard origin/main
echo "$GHCR_TOKEN" | docker login ghcr.io -u <user> --password-stdin
docker compose pull
docker compose up -d --remove-orphans
sleep 30 && tb status
```

**Rollback to a specific commit:**

```bash
ssh <user>@theeyebeta-mac
cd ~/theeyebeta
git log --oneline -10
git reset --hard <sha>
docker compose up -d --force-recreate
tb status
```

---

## Incident Response

1. **Stop trading** — `docker compose stop agent-runtime broker-adapter-alpaca oms`
2. **Identify** — `tb status` → which service is red?
3. **Logs** — `tb logs <svc>` → first exception, first connection error
4. **Infra** — `docker compose ps` → any exited containers?
5. **Grafana** — check dashboards for error-rate spikes (Tailscale required)
6. **Resolve or rollback** — fix + redeploy, or `git reset --hard` (see above)
7. **Resume** — `docker compose start oms broker-adapter-alpaca agent-runtime`
8. **Post-mortem** — open a GitHub Issue; attach relevant logs

> **15-minute rule:** if the root cause isn't clear in 15 minutes, rollback first,
> investigate second.

---

## §15 Operations Runbook (from architecture.md)

_Reproduced verbatim from [architecture.md §15](architecture.md#15-operations-runbook)._

### Quick reference

```bash
# Check system health
tb status

# View logs
tb logs <service-name>
make logs-<service-name>

# Deploy a single service manually
tb deploy <service-name>    # requires confirmation

# Emergency stop
docker compose stop <service-name>

# Full restart
make down && make up

# Rollback to previous commit
cd ~/theeyebeta
git log --oneline -5          # find the good commit
git reset --hard <sha>
docker compose up -d --force-recreate
```
