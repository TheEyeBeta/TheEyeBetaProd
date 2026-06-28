# Local → Prod feature parity

Bring **TheEyeBetaLocal** capabilities onto the **TheEyeBetaProd** host without
abandoning Prod's microservice architecture.

## Current state (2026-06-18)

| Local feature | Prod today | Parity path |
|---------------|------------|-------------|
| `./theeye` CLI | `uv run tb` (partial overlap) | `./theeye` shim → `tb` + Local fallback |
| Trade engine (10 workers, 24/7) | Timer workers only; engine **masked** | Enable Local engine unit on host |
| Trask daemon (`:8090`) | DB tables + admin API only; Trask **masked** | Enable Local Trask unit (after engine) |
| News (Finnhub + NewsAPI) | RSS → `news_articles` only | Engine news worker + `news-bridge` → `market_news` |
| Main API `:8000` + WebSocket | DataAPI `:7000` (no WS) | Keep DataAPI; optional Local API later |

## Enable stack (operator)

From **TheEyeBetaProd** repo on the server:

```bash
# Review warnings, then:
sudo bash deploy/enable_local_parity_stack.sh --confirm

# Verify
uv run tb trask status
curl -s http://127.0.0.1:8090/health
curl -s http://127.0.0.1:7000/health
./theeye now status
```

This script:

1. Installs `theeyebeta-engine.service` and `theeyebeta-trask.service` from Local
2. Unmasks and starts engine → Trask (Trask depends on engine)
3. Enables `theeye-news-ingest.timer` (Prod RSS)
4. Enables `theeye-news-bridge.timer` (RSS → `market_news` for DataAPI)
5. Installs `./theeye` CLI shim in Prod repo root

## Conflicts to understand

- **RAM:** Local engine uses ~1.5–1.7 GiB. On a 16–32 GiB host, monitor with `free -h`.
- **Duplicate ingest:** Engine price/news workers overlap Prod timers. Safe for now; long-term
  consolidate into Prod `workers/` or disable overlapping timers.
- **Schema:** Engine writes **`public.*`** tables; Prod canonical path is **`theeyebeta.*`**.
  DataAPI reads `theeyebeta` — use bridge workers and `latest_snapshot_worker`.
- **Signals:** Engine writes `public.signals`; Prod `theeyebeta.signals` needs cutover (#3).

## CLI mapping

| Local `./theeye` | Prod equivalent |
|------------------|-----------------|
| `now status/price/indicators` | `tb now …` |
| `quant returns/corr/var` | `tb quant …` |
| `trask status/dashboard` | `tb trask …` |
| `engine ping/status` | Local `./theeye engine …` (IPC to engine) |
| `trask digest/worker restart` | Local `./theeye trask …` (Trask daemon) |
| `pipeline daily` | `tb pipeline …` or `tb workers run daily-pipeline` |

## CLI (quant parity)

All Local `./theeye quant` commands are available via `tb quant`:

```bash
uv run tb quant returns AAPL,MSFT --start 2025-01-01 --end 2025-12-31
uv run tb quant sharpe-opt AAPL,MSFT,GOOGL --start 2025-01-01 --end 2025-12-31
uv run tb quant var AAPL,MSFT --confidence 0.95 --window 252
uv run tb quant pairs AAPL,MSFT,GOOGL --max-pairs 5
uv run tb quant capm AAPL SPY
uv run tb quant mc-option 100 105 0.5 0.25 --type call
```

Or use `./theeye quant …` (shim routes to `tb`).

## News pipeline

1. RSS ingest → `theeyebeta.news_articles` (with ticker tagging)
2. Engine news worker → `public.market_news` (when engine running)
3. `scripts/sync_market_news.py` → `theeyebeta.market_news` (DataAPI reads this)

```bash
uv run tb workers run news-ingest
uv run tb workers run news-bridge
uv run tb now news AAPL
```

Timers: `theeye-news-ingest.timer`, `theeye-news-bridge.timer`


```bash
sudo systemctl stop theeyebeta-trask theeyebeta-engine
sudo systemctl disable theeyebeta-trask theeyebeta-engine
sudo systemctl mask theeyebeta-trask theeyebeta-engine
```

## Long-term (proper port into Prod)

1. Port engine workers into `workers/` as optional long-running systemd template units
2. Port Trask sentinel loop into Prod or extend `heartbeat-monitor` + admin Trask UI
3. Merge remaining `./theeye quant` commands into `tb quant`
4. Point DataAPI news routes at `news_articles` OR keep unified `market_news` bridge
5. Retire `public.*` writes once `theeyebeta.*` parity is verified
