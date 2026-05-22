# Headless Operations

Day-to-day operations on the production Mac mini via the `tb` CLI and `make` targets.
See also [architecture.md §15](architecture.md#15-operations-runbook).

## `tb` CLI Reference

> `tb` is the theeyebeta management CLI, installed from `tb/` via PyPI as `tb-theeyebeta-cli`.
> It SSH-tunnels to the Mac mini over Tailscale when run remotely.

```
tb status                    Show health of all services (green/yellow/red)
tb logs <svc>                Tail logs for a service
tb restart <svc>             Restart a service (requires confirmation)
tb deploy <svc>              Pull latest image + restart (requires confirmation)
tb deploy --all              Rolling deploy of all services (requires confirmation)

tb backtest run <config>     Submit a backtest job
tb backtest status <id>      Check backtest job status
tb backtest results <id>     Download results to MinIO

tb db migrate                Run alembic upgrade head (LOCAL only without --prod flag)
tb db migrate --prod         Run migrations on production (requires confirmation)
tb db shell                  Open psql session on production DB

tb secrets decrypt <env>     Decrypt secrets/dev.enc.yaml → .env
tb secrets edit <env>        Open sops editor for a secrets file
```

## Common Tasks

### Check system health

```bash
tb status
# or from the repo:
make status
```

### Deploy after a hotfix

```bash
git commit -m "fix(oms): ..."
git push origin main
# Deploy workflow triggers automatically via GitHub Actions
# Monitor: https://github.com/<org>/theeyebeta/actions
```

### Manual single-service restart

```bash
tb restart market-service     # prompts for confirmation
```

### Run a backtest

```bash
tb backtest run services/backtest-engine/configs/sp500_momentum.yaml
tb backtest status <job-id>
```

### View live logs

```bash
tb logs data-ingestion
# or
make logs-data-ingestion
```

### Emergency: stop all trading

```bash
# From Mac mini directly:
docker compose stop agent-runtime broker-adapter-alpaca oms
```

### Apply a schema migration to production

```bash
# ALWAYS review the migration plan first
tb db migrate --prod --dry-run
# Then apply:
tb db migrate --prod    # requires confirmation + shows plan
```

## Deploy Runbook

Automated deploys happen via `.github/workflows/deploy.yml` on every push to `main`.

**Manual deploy steps (emergency):**

```bash
ssh <user>@theeyebeta-mac
cd ~/theeyebeta
git fetch origin && git reset --hard origin/main
echo "$GHCR_TOKEN" | docker login ghcr.io -u <user> --password-stdin
docker compose pull
docker compose up -d --remove-orphans
sleep 30
tb status
```

**Rollback:**

```bash
ssh <user>@theeyebeta-mac
cd ~/theeyebeta
git log --oneline -10        # find the last good commit
git reset --hard <sha>
docker compose up -d --force-recreate
tb status
```

## Incident Response

1. Check `tb status` — identify the unhealthy service(s).
2. Check logs: `tb logs <svc>` — look for exceptions, connection errors.
3. Check infra: `docker compose ps` — are all containers running?
4. Check Grafana dashboards at http://localhost:3000 (Tailscale required).
5. If unable to resolve in 15 minutes — stop trading:
   ```bash
   docker compose stop agent-runtime broker-adapter-alpaca oms
   ```
6. Open a GitHub Issue with logs (template in `.github/ISSUE_TEMPLATE/incident.md`).
