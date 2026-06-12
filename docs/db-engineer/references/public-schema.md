# public Schema Reference — Core Market Data Engine

**Report date**: 2026-06-09 (post Massive.com expansion)

## Scale Summary

| Table | Rows | Notes |
|---|---|---|
| `tickers` | **35,772** | Was 511 — Massive.com expansion complete |
| `price_daily` | **10,680,383** | y2021–y2026 populated |
| `ind_technical_daily` | **10,671,378** | |
| `ind_risk_daily` | **10,676,370** | |
| `returns_snapshot_daily` | **10,667,954** | High churn — autovacuum tuned |
| `signals` | **144,016,848** | Largest table by row count — never SELECT * |
| `score_audit_log` | **20,072,428** | Live immutable compliance backbone |
| `trask_audit_events` | **26,665,648** | Legitimate high-volume audit (NOT a payload bug) |
| `corporate_actions` | **468,085** | Was 7,833 |
| `latest_snapshot` | **12,716** | Was 501 — one row per active ticker |
| `audit_data_gaps` | **162,273 open** | Was 1,505 |

---

## Partition Map

```
public.price_daily          (10,680,383) → _y2021 … _y2026 (+ _y2027 empty)
public.ind_technical_daily  (10,671,378) → _y2021 … _y2026
public.ind_risk_daily       (10,676,370) → _y2021 … _y2026
public.ind_valuation_daily  (y2021+)     → _y2021 … _y2026  (was y2026-only)
```

**Partition row samples** (from 2026-06-09 bloat report):

| Partition | Live rows | Dead rows | Dead% |
|---|---|---|---|
| `price_daily_y2025` | 2,554,282 | 488,622 | 16.0% |
| `price_daily_y2026` | 1,249,215 | 227,065 | 15.4% |
| `price_daily_y2023` | 1,940,468 | 164,943 | 7.8% |
| `ind_technical_daily_y2024` | 2,195,896 | 319,488 | 12.7% |
| `ind_technical_daily_y2022` | 1,781,677 | 143,100 | 7.4% |
| `ind_valuation_daily_y2026` | 66,121 | 12,085 | 15.5% |

**Key insight**: `ind_valuation_daily` now spans y2021–y2026 (not y2026-only). Always include
`date` in WHERE — a missing date filter scans millions of rows across all year partitions.

---

## tickers

```sql
ticker_id BIGINT PRIMARY KEY
ticker VARCHAR(...) NOT NULL
is_active BOOLEAN
-- 35,772 rows after Massive.com expansion
```

Cross-schema access to theeyebeta requires `theeyebeta.public_ticker_map` — only 511 instruments
are bridged to `theeyebeta.instruments`.

---

## price_daily Columns

```sql
ticker_id BIGINT NOT NULL → tickers.ticker_id
date DATE NOT NULL
open, high, low NUMERIC(18,6)
close NUMERIC(18,6) NOT NULL  -- CHECK close > 0
adj_close, vwap NUMERIC(18,6)
volume BIGINT                 -- CHECK volume >= 0
data_source VARCHAR(50) DEFAULT 'yfinance'
ingestion_timestamp TIMESTAMPTZ DEFAULT now()
data_checksum VARCHAR(64)
data_version INT DEFAULT 1
PRIMARY KEY (ticker_id, date)  -- on each child partition
```

Query pattern:
```sql
SELECT date, close, volume
FROM public.price_daily
WHERE ticker_id = $1 AND date >= '2025-01-01'  -- partition pruning mandatory
ORDER BY date DESC LIMIT 30;
```

---

## ind_technical_daily Columns

```sql
ticker_id, date  -- composite PK
sma_10, sma_50, sma_200, ema_10, ema_50, ema_200, ema_12, ema_26 NUMERIC(18,6)
rsi_14 NUMERIC(10,4)
macd, macd_signal, macd_hist NUMERIC(18,6)
roc_10, roc_20 NUMERIC(12,6)
golden_cross_sma, death_cross_sma BOOLEAN
momentum_rank_12_1 NUMERIC(6,2)
price_field TEXT  -- 'adj_close' | 'close'
compute_version TEXT
as_of_date DATE
computed_at TIMESTAMPTZ DEFAULT now()
```

---

## ind_risk_daily Columns

```sql
ticker_id, date
atr_14 NUMERIC(18,6)
hist_vol_20d, hist_vol_60d NUMERIC(12,6)
beta_sp500_60d NUMERIC(12,6)
worst_drop_1d, worst_drop_5d, worst_drop_10d NUMERIC(12,6)
max_drawdown_1y, max_drawdown_2y NUMERIC(12,6)
sharpe_60d, sortino_60d, calmar_1y NUMERIC(12,6)
as_of_date DATE
computed_at TIMESTAMPTZ DEFAULT now()
```

---

## signals — 144 Million Rows

```sql
signal_id BIGINT PK (sequence)
ticker_id BIGINT → tickers.ticker_id
ts TIMESTAMPTZ NOT NULL
strategy_name VARCHAR(64) NOT NULL
signal VARCHAR(16)  -- 'BUY' | 'SELL' | 'HOLD' | 'STRONG_BUY' | 'STRONG_SELL'
confidence NUMERIC(5,4)
entry_price, target_price, stop_loss NUMERIC(18,6)
metadata JSONB
UNIQUE (ticker_id, ts, strategy_name)
```

**144,016,848 rows**. The `metadata JSONB` column can be large per row.
**NEVER SELECT \***. Always column list + `ts` range + `LIMIT`:
```sql
SELECT signal_id, ticker_id, ts, strategy_name, signal, confidence
FROM public.signals
WHERE ticker_id = $1 AND ts >= $2
ORDER BY ts DESC LIMIT $3;
```

Mirrored in theeyebeta as `theeyebeta.signals` hypertable (8.9M rows, 2 chunks) with
`source_public_signal_id` FK back to `public.signals.signal_id`.

---

## score_audit_log — 20 Million Rows, Immutable

```sql
audit_id BIGINT PK
ticker_id BIGINT → tickers.ticker_id
scored_at TIMESTAMPTZ NOT NULL
composite_score, quality_score, growth_score, valuation_score NUMERIC(10,4)
financial_health_score, cash_flow_quality_score NUMERIC(10,4)
momentum_score, risk_score NUMERIC(10,4)
long_term_attractiveness_score, short_term_setup_score NUMERIC(10,4)
composite_signal VARCHAR(16)
investment_stance VARCHAR(32)
stance_confidence VARCHAR(16)
score_drivers JSONB NOT NULL DEFAULT '{}'  -- heavy column
data_hash CHAR(64) NOT NULL
computation_version VARCHAR(64) NOT NULL
```

**20,072,428 rows** — live and actively written. **IMMUTABLE** — no UPDATE/DELETE.
Previously flagged as "0 rows suspicious" — that flag is **retracted**.

---

## returns_snapshot_daily — Pre-computed Performance Cache

```sql
ticker_id, date  -- composite PK
ret_1w, ret_1m, ret_3m, ret_6m, ret_9m, ret_ytd, ret_1y NUMERIC(12,6)
price_field TEXT
computed_at TIMESTAMPTZ NOT NULL
compute_version TEXT
```

**10,667,954 rows**. Recomputed frequently — autovacuum tuning required (see autovacuum-tuning.md).

---

## corporate_actions

```sql
-- 468,085 rows (was 7,833)
-- theeyebeta.corporate_actions mirrors with source_public_action_id FK
```

---

## macro_regimes — Daily Macro Classification

```sql
id BIGINT PK
as_of_date DATE UNIQUE NOT NULL
fed_funds_rate, yield_10y, yield_2y, spread_2s10s NUMERIC(8,4)
vix, dxy NUMERIC(8,4)
hy_oas_bps NUMERIC(8,2)
rate_environment, yield_curve, credit_environment VARCHAR(16)
volatility_regime, dollar_regime VARCHAR(16)
style_tilts JSONB NOT NULL DEFAULT '{}'
sp500_level, sp500_change_pct, nasdaq_level, nasdaq_change_pct NUMERIC(12,4)
cpi, gdp NUMERIC
computed_at TIMESTAMPTZ NOT NULL
```

Mirrored as `theeyebeta.macro_regime_snapshots` (1 row currently).

Point-in-time backtest query:
```sql
SELECT * FROM public.macro_regimes
WHERE as_of_date <= :backtest_date
ORDER BY as_of_date DESC LIMIT 1;
```

---

## latest_snapshot — Wide Denormalized Cache

**12,716 rows** (was 501) — one row per active ticker, ~71 columns.
Primary table for real-time UI queries. **Do NOT use for historical queries.**

theeyebeta mirror: `theeyebeta.latest_snapshots` (501 rows, 72 cols, keyed on `instrument_id`).

---

## Materialized Views (NEW)

```sql
public.mv_ma_1y    -- 1-year moving average cache
public.mv_price_2y -- 2-year price history cache
```

Use these for rolling-window lookups instead of scanning `price_daily` partitions:
```sql
SELECT * FROM public.mv_price_2y WHERE ticker_id = $1;
SELECT * FROM public.mv_ma_1y WHERE ticker_id = $1;
```

Refresh policy: check application/worker schedule before assuming freshness.

---

## Compliance Tables

### public.compliance_log (IMMUTABLE)
Append-only, one row per `approve_trade()` call. `check_results JSONB` stores per-check pass/fail.
Index `compliance_log_rejected WHERE approved = false` for fast rejection queries.

### public.restricted_list
`BLACKLIST` = hard block; `GREY_LIST` = override required; `WATCH_LIST` = alert only.
Expired entries retained for audit — never delete. Query `active_restricted_list` VIEW.

---

## TRASK System Tables

```
trask_components         — 24 registered system components
trask_circuit_breakers   — 18 circuit breakers
trask_audit_events       — 26,665,648 rows (high-volume operational audit — NOT a bug)
trask_command_log        — Command execution log
trask_email_log          — Email notification log
trask_status             — Key-value system state (autovacuumed — no longer emergency)
worker_heartbeats        — Worker liveness
engine_status            — Key-value status (autovacuumed — no longer emergency)
```

**Retracted**: previous "9.8 GB for 646 rows = payload bug" flag on `trask_audit_events`.
Current volume (26.7M rows) is legitimate audit traffic. Query with event_type + date filters + LIMIT.

---

## audit_data_gaps

**162,273 open gaps** as of 2026-06-09 (was 1,505). Check before assuming data completeness:
```sql
SELECT dataset_type, severity, remediation_state, COUNT(*) AS gap_count
FROM public.audit_data_gaps
WHERE remediation_state = 'OPEN'
GROUP BY 1, 2, 3 ORDER BY severity DESC;
```

---

## Fundamentals Tables

| Table | Rows | Bloat note |
|---|---|---|
| `fund_income_q` | 117,828 live | 13,807 dead (10.5%) — tune autovacuum |
| `fund_balance_q` | — | 6,390 dead (new) — tune autovacuum |
| `fund_cashflow_q` | — | |

theeyebeta mirrors exist with `instrument_id` FK (smaller row counts — 511-instrument universe).

---

## Useful Views

```sql
SELECT * FROM public.active_restricted_list WHERE restriction_type = 'BLACKLIST';
SELECT * FROM public.audit_open_gaps_summary;
SELECT * FROM public.audit_worker_status_today;
SELECT * FROM public.compliance_rejections_7d;
SELECT * FROM public.fund_income_q_latest WHERE ticker_id = $1;
SELECT * FROM public.fund_balance_q_latest WHERE ticker_id = $1;
SELECT * FROM public.mv_price_2y WHERE ticker_id = $1;
SELECT * FROM public.mv_ma_1y WHERE ticker_id = $1;
```

---

## Cross-Schema Query Pattern

When agent code needs public data keyed to theeyebeta instruments:
```sql
SELECT pd.date, pd.close, itd.rsi_14
FROM theeyebeta.public_ticker_map ptm
JOIN public.price_daily pd ON pd.ticker_id = ptm.public_ticker_id
JOIN public.ind_technical_daily itd
  ON itd.ticker_id = pd.ticker_id AND itd.date = pd.date
WHERE ptm.instrument_id = $1
  AND pd.date >= '2025-01-01'
ORDER BY pd.date DESC LIMIT 30;
```
