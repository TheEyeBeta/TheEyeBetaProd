# tb CLI Reference (TheEyeBetaProd)

> Sole operator CLI for the Mac mini. All queries use `theeyebeta.*` schema.
> Invoke: `uv run tb <command>` from repo root.

## Quick start

```bash
uv run tb status
uv run tb meta doctor
uv run tb prelive
uv run tb meta cheat
uv run tb --install-completion   # bash/zsh completion
```

## Command tree

### Platform ops

| Command | Description |
|---------|-------------|
| `tb status [--json]` | Universe counts, Docker health, timers, heartbeats |
| `tb prelive [--json]` | 12-check go/no-go harness |
| `tb meta doctor [--json]` | DB, disk, timers quick check |
| `tb meta cheat` | Operator cheat sheet |
| `tb meta version` | CLI version |

### Live data (`tb now`)

| Command | Description |
|---------|-------------|
| `tb now status` | Engine / universe summary |
| `tb now price <SYMBOL>` | Latest daily close |
| `tb now indicators <SYMBOL> [--long]` | Latest technical indicators |
| `tb now news <SYMBOL>` | Recent news (if table present) |
| `tb now diagnose <SYMBOL>` | Why indicators may be missing |

### Canonical / intraday (Prod extras)

| Command | Description |
|---------|-------------|
| `tb canonical status` | Price + indicator coverage |
| `tb canonical gaps` | Open `audit_data_gaps` |
| `tb intraday coverage [--date]` | Bucket fill rate vs ~4.6k universe |
| `tb intraday latest [--symbol]` | Recent 15m bars |

### Workers & pipeline

| Command | Description |
|---------|-------------|
| `tb workers list` | Runnable worker aliases |
| `tb workers run <name> [--dry-run] [--date] [--force]` | Run one worker |
| `tb workers tail <name> [-f]` | journalctl for systemd unit |
| `tb workers schedule` | List theeye timers |
| `tb pipeline daily [--date] [--dry-run]` | Daily indicator pipeline |
| `tb pipeline status` | Recent `daily_pipeline` runs |
| `tb pipeline report <DATE>` | Price/indicator counts |

### Trask

| Command | Description |
|---------|-------------|
| `tb trask status` | Breakers + FAILED components |
| `tb trask workers` | All registered components |
| `tb trask dashboard --once` | Rich component table |
| `tb trask events` | Recent audit alerts |
| `tb trask findings` | Open data gaps |
| `tb trask audit` | Recent worker_runs |
| `tb trask worker status [id]` | Worker component status |
| `tb trask sentinel status [id]` | Sentinel status |

### Universe & instruments

| Command | Description |
|---------|-------------|
| `tb universe sync --tier eod\|intraday [--apply]` | Cap-tier selection |
| `tb universe tiers` | EOD vs intraday counts |
| `tb universe list [--all]` | List instruments |
| `tb universe search <PREFIX>` | Symbol search |
| `tb universe coverage` | Canonical freshness |
| `tb instrument list/add/remove` | Instrument management |

### Data engine

| Command | Description |
|---------|-------------|
| `tb prices freshness/range/sample/ingest` | Daily price ops |
| `tb prices gaps detect` | Gap sentinel |
| `tb indicators latest/compute/null-report` | Technical indicators |
| `tb returns latest/leaderboard` | Return analytics |
| `tb snapshot quote/get/movers` | Packaged snapshots |
| `tb export prices/schema` | CSV/JSON export |
| `tb fundamentals latest/coverage` | Fundamentals (when populated) |

### Analytics

| Command | Description |
|---------|-------------|
| `tb plot price/ema/sma/volume/rsi/all <SYMBOL>` | Terminal chart summaries |
| `tb quant returns/corr/var <SYMBOL>` | Quant analytics |

### Research

| Command | Description |
|---------|-------------|
| `tb backtest run <config.json>` | Submit to backtest-engine :7100 |
| `tb backtest status/results <run_id>` | Job status / results |
| `tb strategies list/describe` | Strategy stubs |
| `tb signals latest/scan` | Signal stubs |
| `tb sql query "SELECT ..."` | Read-only SQL |
| `tb sql explain "SELECT ..."` | Query plan |

### Infra

| Command | Description |
|---------|-------------|
| `tb logs <svc> [-f]` | Docker or worker journal |
| `tb restart <svc> [-y]` | Docker compose restart |
| `tb deploy [<svc>\|--all] [-y]` | Pull + up --wait |
| `tb db migrate [--dry-run] [--prod]` | Alembic migrations |
| `tb db shell/ping/verify/stats` | DB utilities |
| `tb secrets decrypt/edit <env>` | sops wrappers |
| `tb config show/validate/env check` | Env inspection |
| `tb snapshots backfill/verify` | Packaged snapshots |

## Schema notes

- Prices: `theeyebeta.prices_daily` / `prices_intraday` by `instrument_id`
- Indicators: `theeyebeta.ind_technical_daily`
- Ops: `theeyebeta.worker_runs`, `worker_heartbeats`, `trask_*`
- No `public.*` or TheEyeBetaLocal imports

## See also

- [headless-operations.md](headless-operations.md) — emergency runbook
- [deploy/MACMINI_OPERATOR_RUNBOOK.md](../deploy/MACMINI_OPERATOR_RUNBOOK.md) — Mac mini ops
