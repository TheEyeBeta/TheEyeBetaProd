# theeyebeta Schema Reference — Agent Trading System

**Report date**: 2026-06-09

## Overview

The `theeyebeta` schema is the agent trading system plus mirrored market data keyed on `instrument_id`.
It uses UUIDs for most PKs, pgvector HNSW indexes, a hash-chained audit log, and TimescaleDB for
price and signal time-series.

**Critical migration state**: most data tables have both `ticker_id` (legacy) and `instrument_id`
(correct FK). All new code must use `instrument_id`. Cross-schema joins require `public_ticker_map`.

---

## Cross-Schema Bridge

```
public.tickers.ticker_id
    ↔ theeyebeta.public_ticker_map.public_ticker_id  (511 rows)
    ↔ theeyebeta.public_ticker_map.instrument_id
    ↔ theeyebeta.instruments.id
```

```sql
-- public_ticker_map columns
public_ticker_id BIGINT  -- FK → public.tickers.ticker_id
instrument_id    BIGINT  -- FK → theeyebeta.instruments.id
symbol           TEXT
exchange_id      BIGINT  -- FK → theeyebeta.exchanges.id
synced_at        TIMESTAMPTZ
```

Only 511 instruments are bridged (Massive.com active universe). Do not assume every
`public.tickers` row (35,772) has a theeyebeta instrument.

---

## Core Entity Map

```
theeyebeta.exchanges (7 rows)
    └── theeyebeta.instruments
            ├── theeyebeta.public_ticker_map (511 rows — BRIDGE)
            ├── theeyebeta.prices_daily (HYPERTABLE, 62 chunks, COMPRESSED)
            ├── theeyebeta.prices_intraday (HYPERTABLE)
            ├── theeyebeta.signals (HYPERTABLE, 2 chunks, 8,945,029 rows)
            ├── theeyebeta.price_ticks (3,134,275 rows)
            ├── theeyebeta.corporate_actions (+ source_public_action_id)
            └── theeyebeta.fundamentals_company (507 rows)

theeyebeta.accounts
    └── theeyebeta.portfolios
            ├── theeyebeta.positions (UNIQUE: portfolio_id, instrument_id)
            ├── theeyebeta.orders → theeyebeta.executions
            ├── theeyebeta.compliance_checks
            └── theeyebeta.risk_metrics

theeyebeta.strategies
    └── theeyebeta.backtest_runs → theeyebeta.backtest_results
        └── theeyebeta.data_snapshots

theeyebeta.agents (30 active)
    └── theeyebeta.agent_runs
            ├── theeyebeta.agent_decisions → instruments
            ├── theeyebeta.agent_messages
            └── theeyebeta.model_runs (LLM cost; has 'kind' column, default 'completion')

theeyebeta.agent_memory (HNSW: idx_agent_mem_hnsw)
theeyebeta.news_articles (+ source_table, source_public_id)
    → theeyebeta.news_embeddings (HNSW: idx_news_embed_hnsw)
theeyebeta.ticker_news (13,140 rows, instrument_id)
theeyebeta.market_news (8,596 rows)
theeyebeta.news_enriched (30 rows, instrument_id)
theeyebeta.macro_regime_snapshots (1 row — mirror of public.macro_regimes)
theeyebeta.provider_sync_runs (7 rows — data sync job tracking)
theeyebeta.guard_violations → agents, agent_runs
theeyebeta.proposals → agent_runs, backtest_runs
theeyebeta.api_costs

theeyebeta.audit_log (PARTITIONED monthly — hash-chained, append-only)
    ├── audit_log_2026_05 … audit_log_2026_11
```

---

## Mirrored Market Data Tables (instrument_id FK)

These mirror `public.*` tables but keyed on `instrument_id`. Legacy `ticker_id` may still exist.

| theeyebeta table | Rows | public counterpart | Notes |
|---|---|---|---|
| `ind_technical_daily` | 533,422 | `public.ind_technical_daily` (10.7M) | Partial sync — 511 instruments |
| `ind_risk_daily` | 488,216 | `public.ind_risk_daily` (10.7M) | 17 columns |
| `returns_snapshot_daily` | 534,088 | `public.returns_snapshot_daily` (10.7M) | |
| `ind_valuation_daily` | 42,641 | `public.ind_valuation_daily` | y2021+ in public |
| `latest_snapshots` | 501 | `public.latest_snapshot` (12,716) | **Plural** — 72 cols, per instrument |
| `fundamentals_company` | 507 | — | instrument_id FK |
| `fund_balance_q` | 4,708 | `public.fund_balance_q` | instrument_id FK |
| `fund_cashflow_q` | 4,843 | `public.fund_cashflow_q` | instrument_id FK |
| `fund_income_q` | 4,655 | `public.fund_income_q` | instrument_id FK |

Query pattern — always join via bridge when starting from public:
```sql
SELECT ls.*, i.symbol
FROM theeyebeta.latest_snapshots ls
JOIN theeyebeta.instruments i ON i.id = ls.instrument_id
WHERE i.id = $1;
```

---

## Table Deep Dives

### theeyebeta.agents
```sql
id TEXT PRIMARY KEY          -- slug: 'argus-v1', 'iris-main'
department TEXT NOT NULL
role TEXT NOT NULL
model_default TEXT NOT NULL
model_fallback TEXT
constitution_path TEXT NOT NULL
active BOOLEAN DEFAULT true
```
**30 agents** in production (was 3). Referenced by `agent_runs`, `agent_memory`, `guard_violations`.

---

### theeyebeta.agent_runs
```sql
id UUID PRIMARY KEY
agent_id TEXT → agents.id
triggered_by TEXT NOT NULL   -- 'scheduler' | 'manual' | 'api' | 'parent_agent'
parent_run_id UUID → agent_runs.id
snapshot_id UUID → data_snapshots.id
started_at, ended_at TIMESTAMPTZ
status TEXT                  -- 'running' | 'completed' | 'failed' | 'cancelled'
total_input_tokens, total_output_tokens INT
total_cost_usd NUMERIC(10,6)
error TEXT
```
**Index**: `idx_agent_runs_agent_started ON (agent_id, started_at DESC)`

---

### theeyebeta.agent_decisions
```sql
id UUID PRIMARY KEY
run_id UUID → agent_runs.id
instrument_id BIGINT → instruments.id  (nullable for market-level decisions)
market TEXT
decision TEXT  -- CHECK: 'buy' | 'sell' | 'hold' | 'reduce' | 'increase' | 'close'
confidence NUMERIC(4,3)
rationale TEXT
evidence JSONB DEFAULT '{}'
proposed_qty, proposed_price NUMERIC
horizon_days INT
```

---

### theeyebeta.orders — State Machine
```sql
id UUID PRIMARY KEY
client_order_id TEXT UNIQUE NOT NULL  -- idempotency key
broker_order_id TEXT
portfolio_id UUID → portfolios.id
instrument_id BIGINT → instruments.id
decision_id UUID → agent_decisions.id
side TEXT          -- 'buy' | 'sell'
order_type TEXT    -- 'market' | 'limit' | 'stop' | 'stop_limit'
qty NUMERIC(20,6)
limit_price, stop_price NUMERIC(18,6)
time_in_force TEXT DEFAULT 'day'
status TEXT DEFAULT 'pending_approval'
  -- 'pending_approval' | 'approved' | 'rejected' | 'submitted'
  -- | 'partially_filled' | 'filled' | 'cancelled' | 'expired'
approved_by TEXT, approved_at TIMESTAMPTZ
submitted_at TIMESTAMPTZ
filled_qty NUMERIC(20,6) DEFAULT 0
avg_fill_price NUMERIC(18,6)
```

Valid transitions (application layer):
```
pending_approval → approved → submitted → filled / cancelled / rejected
pending_approval → rejected
```

---

### theeyebeta.positions
```sql
id BIGINT PRIMARY KEY (sequence)
portfolio_id UUID → portfolios.id
instrument_id BIGINT → instruments.id
qty NUMERIC(20,6)
avg_entry_price, market_value, unrealized_pnl, realized_pnl NUMERIC(20,6)
opened_at, updated_at TIMESTAMPTZ
UNIQUE (portfolio_id, instrument_id)
```
**Live mutable table** — use `FOR UPDATE` on concurrent fill updates.

---

### theeyebeta.prices_daily (TimescaleDB Hypertable)
```sql
instrument_id BIGINT → instruments.id
ts TIMESTAMPTZ  -- partitioning dimension
open, high, low, close NUMERIC(18,6) NOT NULL
adj_close, vwap NUMERIC(18,6)
volume BIGINT NOT NULL
source TEXT NOT NULL
ingested_at TIMESTAMPTZ DEFAULT now()
UNIQUE: (instrument_id, ts)
```
**62 chunks**, compression active, `segmentby = instrument_id`. Check compression before backfill.

---

### theeyebeta.signals (TimescaleDB Hypertable — NEW)
```sql
instrument_id BIGINT → instruments.id
ts TIMESTAMPTZ
strategy_name, signal, confidence ...
source_public_signal_id BIGINT  -- FK back to public.signals.signal_id
```
**2 chunks, 8,945,029 rows**. Same compression/backfill rules as `prices_daily`.
Never query without `ts` range + `LIMIT`.

---

### theeyebeta.price_ticks
```sql
instrument_id BIGINT → instruments.id
ts TIMESTAMPTZ
price, size, ...
```
**3,134,275 rows**. High-frequency — always filter on `instrument_id` + tight `ts` window.

---

### theeyebeta.audit_log (Hash-Chained, Append-Only)
```sql
id BIGINT (audit_log_id_seq)
ts TIMESTAMPTZ DEFAULT now()
actor TEXT NOT NULL
action TEXT NOT NULL
entity_type, entity_id TEXT NOT NULL
payload JSONB NOT NULL
prev_hash BYTEA
row_hash BYTEA NOT NULL
PRIMARY KEY (id, ts)
```
**Monthly partitions** `audit_log_2026_05` … `_2026_11`. **Never UPDATE/DELETE.**

---

### theeyebeta.model_runs (LLM Cost Tracking)
```sql
id UUID PRIMARY KEY
run_id UUID → agent_runs.id
kind TEXT DEFAULT 'completion'   -- NEW column
provider TEXT, model TEXT
input_tokens, output_tokens INT
cache_read_tokens, cache_write_tokens INT DEFAULT 0
cost_usd NUMERIC(10,6)
latency_ms INT, status TEXT
```

---

### theeyebeta.provider_sync_runs
```sql
-- Tracks data sync jobs from public → theeyebeta mirrors
-- 7 rows as of 2026-06-09 — check before assuming mirror freshness
```

---

### theeyebeta.news_articles
```sql
-- Added columns:
source_table TEXT       -- which public table this was synced from
source_public_id BIGINT -- FK to source row in public schema
```

---

### theeyebeta.corporate_actions
```sql
-- Added column:
source_public_action_id BIGINT  -- FK to public.corporate_actions
```
**public.corporate_actions**: 468,085 rows (was 7,833).

---

### theeyebeta.agent_memory (Vector Store)
```sql
id UUID PRIMARY KEY
agent_id TEXT → agents.id
kind TEXT NOT NULL  -- 'observation' | 'reflection' | 'plan' | 'fact'
content TEXT NOT NULL
embedding vector NOT NULL
metadata JSONB
created_at TIMESTAMPTZ
HNSW: idx_agent_mem_hnsw ON (embedding vector_cosine_ops)
```

---

### theeyebeta.guard_violations
```sql
violation_type TEXT  -- 'position_limit' | 'concentration' | 'drawdown'
                     -- | 'compliance' | 'risk_budget' | 'cooldown' | 'other'
severity TEXT        -- 'warning' | 'breach' | 'critical'
resolution TEXT      -- 'auto_blocked' | 'human_override' | 'acknowledged' | 'pending'
resolved BOOLEAN DEFAULT false
```
**Index**: `idx_guard_violations_unresolved WHERE NOT resolved`

---

## Key Ops Queries

```sql
-- Bridge coverage check
SELECT COUNT(*) AS mapped,
       (SELECT COUNT(*) FROM public.tickers WHERE is_active) AS active_public
FROM theeyebeta.public_ticker_map;

-- Agent cost by kind (new model_runs.kind column)
SELECT DATE(mr.created_at) AS day, mr.kind, ar.agent_id,
       SUM(mr.cost_usd) AS total_cost
FROM theeyebeta.model_runs mr
JOIN theeyebeta.agent_runs ar ON ar.id = mr.run_id
WHERE mr.created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2, 3 ORDER BY 1 DESC, 4 DESC;

-- Open order book
SELECT o.id, o.client_order_id, i.symbol, o.side, o.qty, o.status
FROM theeyebeta.orders o
JOIN theeyebeta.instruments i ON i.id = o.instrument_id
WHERE o.status IN ('pending_approval', 'approved', 'submitted')
ORDER BY o.created_at;

-- Latest theeyebeta signals for an instrument
SELECT ts, strategy_name, signal, confidence
FROM theeyebeta.signals
WHERE instrument_id = $1 AND ts >= NOW() - INTERVAL '7 days'
ORDER BY ts DESC LIMIT 50;

-- Sync job freshness
SELECT * FROM theeyebeta.provider_sync_runs ORDER BY started_at DESC LIMIT 5;
```
