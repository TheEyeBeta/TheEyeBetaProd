# Autovacuum Tuning — TheEyeBeta2025Live

**Report date**: 2026-06-09

## Current Bloat Situation

Scale context: partitioned tables now hold **10M+ live rows per parent**. Dead tuple counts that
were tolerable at 500k scale are now operationally significant at millions of dead rows.

| Table | Live | Dead | Dead% | Action |
|---|---|---|---|---|
| `public.price_daily_y2025` | 2,554,282 | 488,622 | **16.0%** | **VACUUM NOW** |
| `public.price_daily_y2026` | 1,249,215 | 227,065 | **15.4%** | **VACUUM NOW** |
| `public.ind_technical_daily_y2024` | 2,195,896 | 319,488 | **12.7%** | **VACUUM NOW** |
| `public.ind_valuation_daily_y2026` | 66,121 | 12,085 | **15.5%** | **VACUUM NOW** |
| `public.price_daily_y2023` | 1,940,468 | 164,943 | 7.8% | Monitor — tune if rising |
| `public.ind_technical_daily_y2022` | 1,781,677 | 143,100 | 7.4% | Monitor |
| `public.fund_income_q` | 117,828 | 13,807 | 10.5% | Tune autovacuum |
| `public.fund_balance_q` | — | 6,390 | — | **New** — tune autovacuum |
| `public.returns_snapshot_daily` | 10,667,954 | — | — | High churn — keep tuned |

### Retracted / Cleared Flags

| Previous flag | Status |
|---|---|
| `ind_valuation_daily_y2026` "50% dead / 501 rows" | **Resolved** — now 66,121 live rows |
| `engine_status` "83% dead emergency" | **Cleared** — autovacuumed |
| `trask_status` "79% dead emergency" | **Cleared** — autovacuumed |
| `trask_audit_events` "9.8 GB payload bug" | **Retracted** — 26.7M rows is legitimate volume |
| `score_audit_log` "0 rows suspicious" | **Retracted** — 20M live rows |

---

## Immediate Actions

### Step 1: VACUUM Critical Partitions (Maintenance Window)

At 10M+ row scale, `VACUUM` on large partitions can take 30–90 minutes and consume I/O.
Run during low-traffic windows. Do NOT run all partitions simultaneously.

```sql
-- Priority 1: highest dead% on largest partitions
VACUUM (ANALYZE, VERBOSE) public.price_daily_y2025;      -- 488k dead, 16%
VACUUM (ANALYZE, VERBOSE) public.price_daily_y2026;      -- 227k dead, 15%
VACUUM (ANALYZE, VERBOSE) public.ind_technical_daily_y2024;  -- 319k dead, 12.7%
VACUUM (ANALYZE, VERBOSE) public.ind_valuation_daily_y2026;  -- 12k dead, 15.5%

-- Priority 2: monitor partitions approaching threshold
VACUUM (ANALYZE) public.price_daily_y2023;                 -- 165k dead, 7.8%
VACUUM (ANALYZE) public.ind_technical_daily_y2022;         -- 143k dead, 7.4%
```

Verify after each VACUUM:
```sql
SELECT tablename, n_live_tup, n_dead_tup,
       round(n_dead_tup::numeric / NULLIF(n_live_tup + n_dead_tup, 0) * 100, 1) AS dead_pct,
       last_autovacuum
FROM pg_stat_user_tables
WHERE tablename IN ('price_daily_y2025', 'price_daily_y2026',
                    'ind_technical_daily_y2024', 'ind_valuation_daily_y2026')
ORDER BY dead_pct DESC;
```

### Step 2: Fundamentals Table Vacuum

```sql
VACUUM (ANALYZE) public.fund_income_q;
VACUUM (ANALYZE) public.fund_balance_q;
```

---

## Autovacuum Tuning SQL

Defaults (`scale_factor=0.2, threshold=50`) are far too lazy for 10M+ row partitions.
At 0.2 scale factor, autovacuum waits for **2M+ dead tuples** before triggering on a 10M partition.

### Partitioned Daily Tables (10M+ rows each)

Apply per-partition settings on the highest-churn year partitions:

```sql
-- price_daily: y2025 and y2026 are actively written — most aggressive
ALTER TABLE public.price_daily_y2025 SET (
  autovacuum_vacuum_scale_factor = 0.01,   -- vacuum at 1% dead (~25k on 2.5M live)
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_analyze_threshold = 500
);
ALTER TABLE public.price_daily_y2026 SET (
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_scale_factor = 0.005,
  autovacuum_analyze_threshold = 500
);

-- price_daily y2023: monitor tier
ALTER TABLE public.price_daily_y2023 SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 2000
);

-- ind_technical_daily: y2024 worst bloat
ALTER TABLE public.ind_technical_daily_y2024 SET (
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 1000
);
ALTER TABLE public.ind_technical_daily_y2022 SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 2000
);

-- ind_valuation_daily y2026
ALTER TABLE public.ind_valuation_daily_y2026 SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 500
);
```

### High-Churn Non-Partitioned Tables

```sql
-- returns_snapshot_daily: 10.7M rows, recomputed on every scoring run
ALTER TABLE public.returns_snapshot_daily SET (
  autovacuum_vacuum_scale_factor = 0.005,  -- vacuum at 0.5% dead (~53k on 10.7M)
  autovacuum_vacuum_threshold = 500,
  autovacuum_analyze_scale_factor = 0.002,
  autovacuum_analyze_threshold = 200
);

-- latest_snapshot: 12,716 rows, continuously updated UI cache
ALTER TABLE public.latest_snapshot SET (
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 50,
  autovacuum_analyze_scale_factor = 0.01,
  autovacuum_analyze_threshold = 20
);

-- fund_income_q: 117k rows, 10.5% dead
ALTER TABLE public.fund_income_q SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 200
);

-- fund_balance_q: new dead tuple accumulation
ALTER TABLE public.fund_balance_q SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 200
);
```

### TRASK / Engine Tables (Previously Emergency — Now Stable)

```sql
-- engine_status and trask_status: cleared by autovacuum — keep aggressive settings
ALTER TABLE public.engine_status SET (
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 2
);
ALTER TABLE public.trask_status SET (
  autovacuum_vacuum_scale_factor = 0.01,
  autovacuum_vacuum_threshold = 2
);

-- trask_audit_events: 26.7M rows — tune for append-heavy workload
ALTER TABLE public.trask_audit_events SET (
  autovacuum_vacuum_scale_factor = 0.005,
  autovacuum_vacuum_threshold = 1000,
  autovacuum_analyze_scale_factor = 0.002,
  autovacuum_analyze_threshold = 500
);

-- trask_components: constantly updated
ALTER TABLE public.trask_components SET (
  autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_threshold = 10
);
```

### TimescaleDB Hypertables (theeyebeta)

```sql
-- signals: 8.9M rows, 2 chunks — monitor after Massive.com sync ramp
-- No per-table autovacuum override needed yet; watch chunk dead tuples:
SELECT chunk_schema, chunk_name, n_live_tup, n_dead_tup
FROM pg_stat_user_tables st
JOIN timescaledb_information.chunks c
  ON st.relname = c.chunk_name
WHERE c.hypertable_schema = 'theeyebeta' AND c.hypertable_name = 'signals';
```

---

## Monitoring Query

Run weekly — thresholds adjusted for 10M+ row scale:

```sql
SELECT
  schemaname || '.' || tablename AS table_full,
  n_live_tup,
  n_dead_tup,
  CASE WHEN n_live_tup + n_dead_tup > 0
    THEN round(n_dead_tup::numeric / (n_live_tup + n_dead_tup) * 100, 1)
    ELSE 0
  END AS dead_pct,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
  COALESCE(last_autovacuum::text, 'NEVER') AS last_vacuum,
  COALESCE(last_autoanalyze::text, 'NEVER') AS last_analyze
FROM pg_stat_user_tables
WHERE schemaname IN ('public', 'theeyebeta', 'iam')
  AND (
    n_dead_tup > 10000
    OR (n_live_tup > 100000 AND n_dead_tup::float / NULLIF(n_live_tup, 0) > 0.05)
  )
ORDER BY n_dead_tup DESC, dead_pct DESC NULLS LAST;
```

Alert thresholds at new scale:
- **>15% dead** on any partition with >100k live rows → schedule VACUUM
- **>100k dead tuples** on any table → investigate churn source
- **NEVER** on `public.signals` (144M rows) or `public.score_audit_log` (20M rows) — autovacuum only

---

## XID Wraparound Check

With continuous ingestion into 10M+ row partitions, check monthly:

```sql
SELECT datname,
       age(datfrozenxid) AS xid_age,
       pg_size_pretty(pg_database_size(datname)) AS db_size
FROM pg_database
WHERE datname = 'TheEyeBeta2025Live'
ORDER BY xid_age DESC;
-- Alert if age > 1,500,000,000
-- Emergency if age > 1,900,000,000 (PostgreSQL shuts down at 2.1 billion)
```

Long-running transactions on 144M-row `public.signals` are a wraparound risk — kill anything >1 hour.

---

## What NOT To Do

```sql
-- NEVER: VACUUM FULL on 10M+ row partitions during trading hours
-- NEVER: manual VACUUM on public.signals (144M rows) or score_audit_log (20M rows)
-- NEVER: assume trask_audit_events bloat = payload bug (retracted 2026-06-09)
-- NEVER: run VACUUM on all price_daily_y20XX partitions simultaneously
```
