# GRAND VERIFICATION AUDIT — TheEyeBeta2025Live

**Audit date:** 2026-06-12 (UTC+1 host local)  
**Auditor mode:** Read-only — no DB writes, no fixes applied  
**Repos:** `TheEyeBetaProd`, `TheEyeBetaLocal`  
**DB:** PostgreSQL 16.14 + TimescaleDB, database `TheEyeBeta2025Live`  
**Host:** 16 GB RAM Mac mini (Linux)

---

## SECTION 1 — SCHEMA & MIGRATIONS

### 1.1 `public.alembic_version`

**Command:**
```bash
PGPASSWORD='***' psql -h 127.0.0.1 -U postgres -d TheEyeBeta2025Live \
  -c "SELECT version_num FROM public.alembic_version;"
```

**Output:**
```
 version_num
-------------
 20260610_01
```

**Verdict:** PASS — matches expected `20260610_01`.  
**Note:** `tb_app` lacks `SELECT` on `alembic_version`; superuser used (documented).

---

### 1.2 `theeyebeta.alembic_version`

**Command:** same session, `SELECT version_num FROM theeyebeta.alembic_version;`

**Output:**
```
     version_num
----------------------
 0013_prices_intraday
```

**Verdict:** PASS — `≥ 0012_sector_daily`; intraday migration applied.

---

### 1.3 Column counts (39)

**Command:**
```sql
SELECT COUNT(*) FROM pg_attribute a
JOIN pg_class c ON a.attrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname='public' AND c.relname='macro_regimes'
  AND a.attnum > 0 AND NOT a.attisdropped;
-- repeat for theeyebeta.macro_regime_snapshots
```

**Output:** `39` for both tables.

**Verdict:** PASS — `information_schema` returned 0 under `tb_app` (privilege masking); `pg_catalog` is authoritative.

---

### 1.4 Table existence (`to_regclass`)

**Output:**
```
 sector_daily | prices_intraday | macro_indicators
--------------+-----------------+------------------
 sector_daily | prices_intraday | macro_indicators
```

**Verdict:** PASS — all three exist (intraday table present; Phase B schema landed, data empty — see §14).

---

### 1.5 Migration files + `downgrade()`

Files live in **TheEyeBetaLocal** (not copied to Prod tree):

| File | `downgrade()` summary |
|------|----------------------|
| `db/migrations/versions/20260610_01_macro_derived_cols_public.py` | `ALTER TABLE public.macro_regimes DROP COLUMN IF EXISTS` ×16 derived cols |
| `db/migrations/theeyebeta_versions/0011_macro_derived_snapshots.py` | Same 16 columns on `theeyebeta.macro_regime_snapshots` |
| `db/migrations/theeyebeta_versions/0012_sector_daily.py` | `DROP TABLE IF EXISTS theeyebeta.sector_daily` |
| `db/migrations/theeyebeta_versions/0013_prices_intraday.py` | `remove_compression_policy` + `DROP TABLE IF EXISTS theeyebeta.prices_intraday CASCADE` |

**Verdict:** PASS — real reversible downgrades present in Local repo.

---

### 1.6 Revision ID lengths ≤ 32

**Output:** `20260610_01` (11), `0011_macro_derived_snapshots` (28), `0012_sector_daily` (17), `0013_prices_intraday` (20) — all OK.

**Verdict:** PASS

| Check | Verdict |
|-------|---------|
| 1.1–1.6 | PASS (1.1 via postgres superuser) |

---

## SECTION 2 — PRICE DATA INTEGRITY

### 2.1 Per-day coverage 2026-06-02..today

**theeyebeta.prices_daily:**
```
     d      | cnt
------------+-----
 2026-06-02 | 500
 2026-06-03 | 500
 2026-06-04 | 500
 2026-06-05 | 500
 2026-06-08 | 499
 2026-06-09 | 499
 2026-06-10 | 498
 2026-06-11 | 499
```

**public.price_daily (legacy blowout universe):**
```
     d      |  cnt
------------+-------
 2026-06-02 | 12200
 ...
 2026-06-11 |  1221
```

**Verdict:** PASS for **canonical** (`theeyebeta`, all trading days ≥ 475). **FAIL** for **public** row counts (~1.2k–12k, not ≈499). Public is legacy multi-ticker store; canonical path is healthy.

---

### 2.2 Source provenance (canonical)

```
 2026-06-02..05 | public_mirror_backfill | 500
 2026-06-08/09  | yfinance_backfill_prices | 499
 2026-06-10     | massive 495 + yfinance 3
 2026-06-11     | massive 496 + yfinance 3
```

**Verdict:** PASS — narrative matches campaign (mirror → yfinance → massive-dominant). Minor yfinance residual on massive era (3 names).

---

### 2.3 Cross-schema spot check (2026-06-11, 10 names)

All `rel_diff = 0.000000` (max 0.000000 on AMZN).

**Verdict:** PASS

---

### 2.4 Sanity sweep (high<low, non-positive OHLC since 06-08)

**Output:** `bad_rows = 0`

**Verdict:** PASS

---

### 2.5 Chunk hygiene (newest 5 chunks)

Recent chunk `_hyper_7_130_chunk` (2026-06-06..2026-07-06): `is_compressed = f`. Older chunks compressed as expected.

**Verdict:** PASS

---

### 2.6 Duplicate guard

**Output:** 0 rows (`HAVING COUNT(*) > 1`)

**Verdict:** PASS

| Check | Verdict |
|-------|---------|
| 2.1 canonical | PASS |
| 2.1 public | FAIL |
| 2.2–2.6 | PASS |

---

## SECTION 3 — INDICATORS & DERIVED DATA

### 3.1 `ind_technical_daily` counts (06-08..latest)

**theeyebeta:**
```
 2026-06-08 | 499
 2026-06-09 | 499
```
(no rows for 2026-06-10 or 2026-06-11)

**public:**
```
 2026-06-08 | 499
 2026-06-09 | 499
 2026-06-11 | 1056
```

**Verdict:** FAIL — canonical indicators stale vs prices (missing post-06-09); public 06-11 shows legacy-sync bloat (1056).

---

### 3.2 Orphan purge

**Output:** `orphan_cnt = 0` where `instrument_id IS NULL`

**Verdict:** PASS — purge held.

---

### 3.3 `search_path` pin

**File:** `TheEyeBetaLocal/packages/data_access/src/data_access/db.py` lines 32–44:
`connect_args={"options": "-csearch_path=public"}` — present.

**`SHOW search_path;`:** `theeyebeta, public`

**Verdict:** PASS (pin in code). **WARN** — DB default still inverted (deferred item).

---

### 3.4 EMA continuity (AAPL, 06-05..06-11)

| date | beta_close | beta_sma50 | pub_close | pub_sma50 |
|------|------------|------------|-----------|-----------|
| 06-05 | 307.34 | 281.2374 | 307.34 | 281.2374 |
| 06-08 | 301.54 | 282.2104 | 301.54 | 282.2104 |
| 06-09 | 290.55 | 283.0454 | 290.55 | 283.0454 |
| 06-10 | 291.58 | **NULL** | 291.58 | **NULL** |
| 06-11 | 295.63 | **NULL** | 295.63 | 284.7812 |

**Verdict:** FAIL — canonical `sma_50` missing 06-10/11 (daily_pipeline not completing); public partially populated on 06-11 only.

---

### 3.5 Returns / risk tables

**theeyebeta.ind_risk_daily:** no rows ≥ 2026-06-08.  
**public.ind_risk_daily:** 10807 (06-10), 1100 (06-11) — legacy-sync-fed.

**Verdict:** WARN — risk metrics still legacy-public only for recent dates.

| Check | Verdict |
|-------|---------|
| 3.1 | FAIL |
| 3.2 | PASS |
| 3.3 | PASS + WARN (DB default) |
| 3.4 | FAIL |
| 3.5 | WARN |

---

## SECTION 4 — MACRO STACK

### 4.1 `macro_indicators` series

23 distinct `series_code` values including `NONFARM_PAYROLLS`, `PCE_CORE`, `CPIAUCSL` (24 rows), `GDPC1` (8 rows). **ISM_*** series absent (noted).

**Verdict:** PASS (ISM absence documented).

---

### 4.2 Latest snapshot (key fields)

```
as_of_date=2026-06-10
cpi_yoy_pct=3.9470  gdp_qoq_pct=1.6211  cpi_surprise=NULL
labels: rate_environment=unknown, yield_curve=flat, credit_environment=tight,
        volatility_regime=elevated, dollar_regime=unknown  → 3/5 non-unknown
```

**Verdict:** WARN — snapshot date is 06-10, not last trading day 06-11; core computed fields present; `cpi_surprise` NULL by design.

---

### 4.3 Mirror sync (full JSON equality)

**Output:** `full_mirror_equal = t`

**Verdict:** PASS

---

### 4.4 Snapshot history depth

**Output:** `snap_count = 2` (~21 days needed for 30d deltas).

**Verdict:** WARN — young history; expected early-campaign state.

---

### 4.5 Sanity ranges (latest per series)

| Series | Value | Range | OK |
|--------|-------|-------|-----|
| UNEMPLOYMENT_RATE | 4.30 | [3,6] | ✓ |
| IG_OAS | 75.00 | [50,250] | ✓ |
| BREAKEVEN_5Y | 2.44 | [1.5,3.0] | ✓ |
| BREAKEVEN_10Y | 2.33 | [1.5,3.0] | ✓ |
| vix | 19.87 | [8,80] | ✓ |
| hy_oas_bps | 275.00 | [150,1200] | ✓ |

**Verdict:** PASS

---

### 4.6 ISM staleness path

**audit_alerts** (≥ 2026-06-10, ISM): 4 WARN rows (`ISM_MFG` / `ISM_SVC` no observation within 40 days).  
**audit_data_gaps:** 4 WARN rows, `remediation_notes = 'Manual ISM PMI entry required'`.

**Verdict:** PASS — staleness path wired; manual entry still required.

| Check | Verdict |
|-------|---------|
| 4.1, 4.3, 4.5, 4.6 | PASS |
| 4.2 | WARN |
| 4.4 | WARN |

**Section 4 launch gate (prelive):** FAIL — macro snapshot stale vs 06-11.

---

## SECTION 5 — SECTOR FEATURE

### 5.1 `sector_daily` by date (last 5)

```
 as_of_date | cnt
------------+-----
 2026-06-09 |  12
```
(only one trading day present)

**Verdict:** FAIL — expected 12 sectors per day since 06-09; missing 06-10 and 06-11.

---

### 5.2 Latest day quality (2026-06-09)

- `rotation_rank` 1–12 dense ✓  
- `pct_above_sma_*` ∈ [0,100] ✓  
- `n_instruments` sum = 499 ✓  
- `top_contributors` valid JSON arrays of 3 ✓  

**Verdict:** PASS for available day.

---

### 5.3 NULL policy

No rows with NULL `avg_return_1d`, `median_rsi_14`, or `rotation_rank` on latest day.

**Verdict:** PASS (no NULL-metric sectors to exemplify >30% missing rule).

---

### 5.4 ARGOS `sector_context` (in-process builder)

```json
{
  "as_of_date": "2026-06-09",
  "rotation": [ /* ranks 1-12 */ ],
  "breadth": { /* 12 sectors */ },
  "data_gaps": []
}
```

**Verdict:** WARN — builder works but `as_of_date` stale (06-09); prelive ARGOS dry-run also reports `macro_context` + `sector_context` gaps.

| Check | Verdict |
|-------|---------|
| 5.1 | FAIL |
| 5.2–5.3 | PASS |
| 5.4 | WARN |

---

## SECTION 6 — WORKER LIFECYCLE & AUDIT SEMANTICS

### 6.1 Distinct worker/status (72h) + SUCCESS ban

22 distinct `(worker_name, status)` pairs including new workers in terminal states.  
`SELECT COUNT(*) ... WHERE status='SUCCESS'` → **0**.

**Verdict:** PASS

---

### 6.2 Stuck runs (>2h STARTED)

```
run_id=99664  worker_name=daily_pipeline  trade_date=2026-06-10  status=STARTED
started_at=2026-06-12 03:15:33+01  ended_at=NULL
```

BackfillPrices `STARTED` zombies: **0**. CANCELLED rows present in 72h window.

**Verdict:** FAIL — one stuck `daily_pipeline` run.

---

### 6.3 Last-72h run table (selected)

| worker | status | records_written | notes |
|--------|--------|-----------------|-------|
| IntradayIngestionWorker | FAILED | — | 42s duration |
| GapSentinelWorker | COMPLETED | 5 | OK |
| MassiveDailyIngestionWorker | COMPLETED | 498–499 | OK |
| CanonicalPriceMirror | COMPLETED | 458–498 | OK |
| SectorAggregationWorker | COMPLETED | 12 | last 2026-06-10 23:08 |
| GapSentinelWorker | FAILED | — | type deduce bug (early 06-10) |
| daily_pipeline | STARTED | — | **stuck** |

**Verdict:** WARN — failures documented; stuck pipeline is critical.

---

### 6.4 Heartbeats (<26h for daily workers)

`audit_worker_runs` has **no** `HEARTBEAT` rows for new workers.  
`trask_components.last_heartbeat`:

| component_id | last_heartbeat | age |
|--------------|----------------|-----|
| MacroIngestionWorker | 2026-06-10 03:06 | >48h |
| MacroRegimeWorker | 2026-06-10 03:06 | >48h |
| MassiveDailyIngestionWorker | 2026-06-12 03:15 | ~13h |
| SectorAggregationWorker | 2026-06-10 23:08 | >17h |
| GapSentinelWorker | 2026-06-12 08:30 | ~8h |

**Verdict:** FAIL — 4/5 campaign workers stale vs 26h rule (prelive agrees).

---

### 6.5 Trading-day chain (06-10, 06-11)

| Step | 06-10 | 06-11 |
|------|-------|-------|
| MacroIngestion + MacroRegime | COMPLETED (manual 03:06) | **no scheduled run** |
| MassiveDailyIngestionWorker | COMPLETED 03:14 (06-12) | COMPLETED 03:15 (06-12) |
| CanonicalPriceMirror | COMPLETED 03:15 | COMPLETED 03:25 |
| daily_pipeline | **STARTED (stuck)** | **no COMPLETED** |
| SectorAggregationWorker | last COMPLETED 06-09 data | **missing** |

**Verdict:** FAIL — chain broken; timer-fired pipeline failed 06-11 (see §7.3).

| Check | Verdict |
|-------|---------|
| 6.1 | PASS |
| 6.2, 6.4, 6.5 | FAIL |
| 6.3 | WARN |

---

## SECTION 7 — SCHEDULING (timers)

### 7.1 `systemctl list-timers 'theeye-*'`

7 timers: macro, massive-ingest, daily-pipeline, gap-sentinel, sector, intraday-ingest, backup.  
(`theeye-supabase-sync.timer` exists in repo but **not loaded** — 0 timers.)

**Verdict:** PASS (≥5). WARN — supabase timer not deployed.

---

### 7.2 OnCalendar vs spec

| Timer | OnCalendar | Persistent |
|-------|------------|------------|
| macro | Mon..Fri 21:20 UTC | true |
| massive-ingest | Mon..Fri 21:30 UTC | true |
| daily-pipeline | Mon..Fri 21:35 UTC | true |
| gap-sentinel | Mon..Fri 07:30 UTC | true |
| sector | Mon..Fri 22:05 UTC | true |
| intraday-ingest | Mon..Fri *:05,20,35,50 UTC | **false** |
| backup | *-*-* 02:00 UTC | true |

**Verdict:** PASS — matches design.

---

### 7.3 Journal evidence (timer-fired, exit 0)

**`journalctl -u theeye-massive-ingest.service`:** `-- No entries --`  
**`journalctl -u theeye-macro.service`:** `-- No entries --`  
**`journalctl -u theeye-sector.service`:** `-- No entries --`

**`journalctl -u theeye-daily-pipeline.service` (Jun 11 22:35):**
```
asyncpg.exceptions.UniqueViolationError: duplicate key ...
Key (worker_name, trade_date)=(CanonicalPriceMirror, 2026-06-11) already exists.
systemd[1]: ... status=1/FAILURE
```

Recent Massive/Mirror COMPLETED runs at **03:14–03:25 on 06-12** lack matching timer journal lines — likely manual/catch-up, not proven timer-fired.

**Verdict:** FAIL — no evidence of successful timer-fired massive ingest; daily-pipeline timer run exited 1.

---

### 7.4 Trading-calendar skip in code

Examples:
- `workers/daily_pipeline_runner.py` lines 44–70 — `_is_trading_day`, skip with `reason: non_trading_day`
- `workers/massive_ingestion_worker.py` lines 85–91 — non-trading day skip
- `workers/macro_regime_worker.py` lines 140–144 — non-trading skip

**Verdict:** PASS (code evidence).

| Check | Verdict |
|-------|---------|
| 7.1–7.2, 7.4 | PASS |
| 7.3 | FAIL |

---

## SECTION 8 — SENTINEL, GAPS & ALERT HYGIENE

### 8.1 Open gaps

```
 severity | count
----------+-------
 CRITICAL |     2
 WARN     |     4
```

**Verdict:** FAIL — 2 open CRITICAL.

---

### 8.2 Gap 162490 (false freshness CRITICAL)

```
gap_id=162490  severity=CRITICAL  remediation_state=RESOLVED
remediation_notes: ... false positive ... freshness_as_of fixed in gap_sentinel_worker.py ...
```

**Verdict:** PASS — resolved with bug-fix note.

---

### 8.3 `freshness_as_of` tests + reasoning

**Command:** `PYTHONPATH=. uv run pytest tests/unit/test_gap_sentinel_worker.py -q` → **8 passed**.

**Logic** (`gap_sentinel_worker.py` `expected_latest_trading_day`, lines 167–172): before 22:00 UTC post-close cutoff, latest expected trading day is **previous** trading day; `freshness_as_of` uses wall clock for current date (lines 333–352).

**Verdict:** PASS

---

### 8.4 Sentinel dry-run writes nothing

`check_pipeline_calendar_gaps`: `if dry_run: continue` before gap insert (line 68).  
`check_canonical_freshness`: `if violation and not dry_run` before writes (line 236).  
`GapSentinelWorker.execute`: branches on `dry_run` (lines 458–464).

**Verdict:** PASS

---

### 8.5 Triage notes (resolved historical gaps)

Examples: gaps 162491–162495 — CRITICAL pipeline-missing days, `RESOLVED 2026-06-10: duplicate of previous...`

**Verdict:** PASS

---

### 8.6 Calendar sentinel coverage (manual SQL, last 10 trading days)

| calendar_date | pipeline_ok | massive_ok |
|---------------|-------------|------------|
| 05-29 .. 06-09 | f | f |
| 06-10 | f | t |
| 06-11 | f | t |

**Verdict:** FAIL — untriaged missing `daily_pipeline COMPLETED` on 06-10 and 06-11 (matches open CRITICAL gaps 162501, 162502).

| Check | Verdict |
|-------|---------|
| 8.1, 8.6 | FAIL |
| 8.2–8.5 | PASS |

---

## SECTION 9 — GUARDS & DESTRUCTIVE-PATH PROTECTION

### 9.1 Legacy copy guard (`sync_public_to_theeyebeta.py`)

Guard (`_guard_prices_daily_scope`, lines 659–666) runs in `main()` at lines 870–871 **before** `engine.connect()` at line 873.

**Execution test:** BLOCKED — Local env lacks installed deps (`ModuleNotFoundError: sqlalchemy`); `uv run` pulled packages but did not complete guard invocation in audit window.

**Verdict:** PASS from code order + guard text; execution not re-run.

---

### 9.2 Universe-sync guard (`--allow-universe-sync`)

Searched `TheEyeBetaLocal` and `TheEyeBetaProd` — **no implementation**. Docs reference `copy_public_to_theeyebeta.py` (file does not exist). `sync_instruments` / `sync_ticker_map` run unconditionally in `sync_all` (lines 674–675).

**Verdict:** FAIL — Prompt 3 guard not implemented.

---

### 9.3 Mirror bridge TEMPORARY marking

`scripts/mirror_canonical_prices_to_public.py` docstring lines 1–6: `TEMPORARY-BRIDGE`.  
`deploy/systemd/theeye-daily-pipeline.service` ExecStart order:
1. `mirror_canonical_prices_to_public.py --run-type scheduled`
2. `workers.daily_pipeline_runner --run-type scheduled`

**Verdict:** PASS

---

### 9.4 `audit_log` immutability (bounded rg)

Hits only in: migration `REVOKE`, verify scripts with `WHERE false`, admin tests probing denial — no production UPDATE/DELETE paths.

**Verdict:** PASS

| Check | Verdict |
|-------|---------|
| 9.1, 9.3, 9.4 | PASS |
| 9.2 | FAIL |

---

## SECTION 10 — UNIVERSE & MAP SANITY

### 10.1 Active instruments

**Output:** `499`

**Verdict:** PASS

---

### 10.2 CTRA / HOLX delisted

```
 id  | symbol | active | delisted_at
 136 | CTRA   | f      | 2026-06-10
 243 | HOLX   | f      | 2026-06-10
```

**Verdict:** PASS

---

### 10.3 `public_ticker_map` bloat

`map_total = 35772`; `map_active = 499` (bloat ratio unchanged from blowout era — inert rows retained).

**Verdict:** WARN — functional map size correct; table still bloated.

---

### 10.4 Universe queries use `WHERE i.active`

| Worker | Location |
|--------|----------|
| MassiveDailyIngestionWorker | `workers/massive_ingestion_worker.py:249` |
| SectorAggregationWorker | `workers/sector_aggregation_worker.py:53` |
| GapSentinelWorker (freshness denominator) | `workers/gap_sentinel_worker.py:212` |
| IntradayIngestionWorker | `workers/intraday_ingestion_worker.py:58` |

Macro workers: N/A (no instrument universe).

**Verdict:** PASS for price-path workers.

| Check | Verdict |
|-------|---------|
| 10.1–10.2, 10.4 | PASS |
| 10.3 | WARN |

---

## SECTION 11 — BACKUP & DISASTER READINESS

### 11.1 Newest dump

```
-rw-rw-r-- 11G Jun 12 02:37 theeye-20260612-0100.dump
```
Age ~13.6h, size >5 GiB.

**Verdict:** PASS

---

### 11.2 Crontab

```
0 2 * * * .../scripts/backup_db.sh >> /home/the-eye-beta/backups/backup.log 2>&1
```

**Verdict:** PASS (+ `theeye-backup.timer` also present)

---

### 11.3 `backup.log` tail

`[2026-06-12T01:37:48Z] backup completed successfully` (11G, 2267s). Prior 06-11 01:09 failure noted (terminated by user).

**Verdict:** PASS (latest run succeeded)

---

### 11.4 `/tmp/backup_test`

**Output:** absent

**Verdict:** PASS

---

### 11.5 Restore command (not executed)

```bash
pg_restore -d TheEyeBeta2025Live --clean --if-exists \
  /home/the-eye-beta/backups/theeye-20260612-0100.dump
```

**Verdict:** PASS (documented)

---

### 11.6 Disk

`/` 32% used, **64.9% free** on DB data path (prelive).

**Verdict:** PASS

| Check | Verdict |
|-------|---------|
| 11.1–11.6 | PASS |

---

## SECTION 12 — HOST HEALTH

### 12.1 Memory / pressure / load

```
Mem: 15Gi total, 11Gi used, 4.0Gi available, Swap 2.0Gi/4.0Gi used
IO  full avg300=18.32%
MEM full avg300=7.52%
load average: 5.21, 5.75, 3.97  (8 cores)
```

**Verdict:** WARN — IO pressure avg300 >10%; load acceptable; swap in use.

---

### 12.2 Docker

`systemctl is-enabled docker` → **disabled**; no grafana/prometheus containers.

**Verdict:** PASS

---

### 12.3 OOM history

**Command:** `journalctl -k --since '2026-06-08' | grep -i -m 20 oom`  
**Result:** BLOCKED — command exceeded 30s with no output (host I/O pressure).

**Verdict:** BLOCKED

---

### 12.4 Postgres memory vs 16 GB

```
shared_buffers=3974MB  work_mem=15898kB  effective_cache_size=11923MB
```

Tuned for ~16 GB host, not 96 GB fantasy config.

**Verdict:** PASS

---

### 12.5 Legacy daemon (`engine.run`)

`pgrep -af engine.run` — no matches. No evidence of pts/9 legacy double-run.

**Verdict:** PASS — legacy daemon not running; Prompt 3A appears effective.

| Check | Verdict |
|-------|---------|
| 12.1 | WARN |
| 12.2, 12.4, 12.5 | PASS |
| 12.3 | BLOCKED |

---

## SECTION 13 — TRASK & CLI (Prompts 4–5)

> **Cutover update (2026-06-14):** Prod operator surface is **`tb`** in TheEyeBetaProd.
> Legacy `./theeye` canonical subcommands are superseded; runtime audit lives in
> `theeyebeta.worker_runs`, `theeyebeta.worker_heartbeats`, and `theeyebeta.trask_*`.

### 13.1 `trask_components` (new workers + sentinels)

**Expected (post-0020_worker_ops):** 14+ worker components including
`IndicatorComputeWorker`, `daily_pipeline`, `MarketCapFetchWorker`,
`MarketCapThresholdWorker`, plus sentinel pairs.

**Verify:** `uv run tb trask workers`

**Verdict:** PASS when all scheduled workers appear in `theeyebeta.trask_components`.

---

### 13.2 Circuit breakers

`SELECT ... FROM theeyebeta.trask_circuit_breakers WHERE state='open'` → 0 rows.

**Verify:** `uv run tb trask status`

**Verdict:** PASS

---

### 13.3 Platform status (replaces `./theeye canonical status`)

**Verify:** `uv run tb status` — EOD universe ~11,365; intraday eligible ~4,651;
latest daily/intraday bucket timestamps; stale heartbeats list.

**Verdict:** PASS when counts and freshness match live universe tiers.

---

### 13.4 Pre-live go/no-go (replaces `./theeye canonical prelive`)

**Verify:** `uv run tb prelive` — exit 0 with zero FAIL checks.

**Verdict:** PASS after first post-cutover nightly chain (massive + daily pipeline).

---

### 13.5 Worker manual run

**Verify:** `uv run tb workers run indicator-compute --dry-run --date YYYY-MM-DD`

**Verdict:** PASS when dry-run reports `planned` > 0 on a trading day with prices.

---

### 13.6 Legacy `./theeye trask status`

Deprecated — do not use on Prod host after June 19 takeover gate.

**Verdict:** SUPERSEDED by `uv run tb trask status`

| Check | Verdict (2026-06-14) |
|-------|----------------------|
| 13.1–13.2 | PASS (schema + seeds applied) |
| 13.3 | PASS (`tb status` operational) |
| 13.4 | PENDING (heartbeats after first scheduled runs) |
| 13.5 | PASS (dry-run verified) |
| 13.6 | SUPERSEDED |

---

## SECTION 14 — INTRADAY & SUPABASE

### 14.1 `prices_intraday`

Table exists (migration `0013` applied). **0 bars**, 0 instruments.  
`IntradayIngestionWorker` FAILED at 2026-06-12 15:50 (trask state FAILED).

**Verdict:** FAIL — schema deployed, ingestion not operational.

---

### 14.2 Intraday did not touch `prices_daily`

06-10/11 canonical daily counts remain 1 row/instrument/day; no duplicate explosion.

**Verdict:** PASS

---

### 14.3 Supabase v2

No shadow reports in `reports/`. `theeye-supabase-sync.timer` not loaded (0 timers).

**Verdict:** NOT-DEPLOYED (legacy sync sentinel RUNNING in trask; v2 cutover not evidenced)

| Check | Verdict |
|-------|---------|
| 14.1 | FAIL |
| 14.2 | PASS |
| 14.3 | NOT-DEPLOYED |

---

## SECTION 15 — THE FORMAL GATE

### 15.1 `uv run python scripts/prelive_check.py --json`

**Exit code: 1**

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| 1 | MIGRATION HEADS | PASS | public=20260610_01, theeyebeta=0013_prices_intraday |
| 2 | CANONICAL PRICE FRESHNESS | PASS | latest=2026-06-11, 499 rows |
| 3 | MACRO FRESHNESS+SANITY | **FAIL** | snapshot=2026-06-10 < 2026-06-11 |
| 4 | GAPS | **FAIL** | open CRITICAL gaps=2 |
| 5 | CALENDAR SENTINEL | **FAIL** | pipeline missing untriaged 06-10, 06-11 |
| 6 | STUCK RUNS | **FAIL** | daily_pipeline#99664 |
| 7 | CIRCUIT BREAKERS | PASS | open=0 |
| 8 | CROSS-SCHEMA SPOT CHECK | PASS | 10 names, rel diff 0 |
| 9 | ARGOS DRY-RUN | WARN | macro_context, sector_context gaps |
| 10 | HEARTBEATS | **FAIL** | 1/5 fresh |
| 11 | DISK | PASS | 64.9% free |
| 12 | BACKUP RECENCY | PASS | 10.8GiB, 13.6h old |

---

### 15.2 Standing block (synthesis)

| Item | Value |
|------|-------|
| Latest canonical prices | 2026-06-11, 499 rows |
| Latest intraday | none (0 bars) |
| Latest macro snapshot | 2026-06-10 |
| Latest sector_daily | 2026-06-09 (12 rows) |
| Open CRITICAL gaps | 2 (pipeline 06-10, 06-11) |
| Stuck worker | daily_pipeline#99664 STARTED since 06-12 03:15 |

**Verdict:** FAIL — formal gate exit 1.

---

# FINAL SCORECARD

| # | Section | PASS | WARN | FAIL | BLOCKED |
|---|---------|------|------|------|---------|
| 1 | Schema & migrations | 6 | 0 | 0 | 0 |
| 2 | Price data integrity | 5 | 0 | 1 | 0 |
| 3 | Indicators & derived | 2 | 2 | 2 | 0 |
| 4 | Macro stack | 4 | 2 | 1 | 0 |
| 5 | Sector feature | 2 | 1 | 1 | 0 |
| 6 | Worker lifecycle | 1 | 1 | 3 | 0 |
| 7 | Scheduling | 3 | 0 | 1 | 0 |
| 8 | Sentinel & gaps | 4 | 0 | 2 | 0 |
| 9 | Guards | 3 | 0 | 1 | 0 |
| 10 | Universe & map | 3 | 1 | 0 | 0 |
| 11 | Backup & DR | 6 | 0 | 0 | 0 |
| 12 | Host health | 3 | 1 | 0 | 1 |
| 13 | TRASK & CLI | 2 | 0 | 0 | 1 |
| 14 | Intraday & Supabase | 1 | 0 | 1 | 0 |
| 15 | Formal gate | 5 | 1 | 6 | 0 |

---

## LAUNCH BLOCKERS

1. **§8.1 / §15 — 2 open CRITICAL gaps (162501, 162502)**  
   Evidence: `Trading day 2026-06-11/06-10 has no daily_pipeline COMPLETED audit_worker_runs row.`  
   **Action:** Clear stuck `daily_pipeline#99664`, fix `CanonicalPriceMirror` duplicate scheduled-run collision, re-run nightly pipeline to COMPLETED; resolve gaps.

2. **§6.2 / §15 — Stuck `daily_pipeline` STARTED >2h (run_id 99664)**  
   Evidence: `started_at=2026-06-12 03:15:33`, `ended_at=NULL`.  
   **Action:** Mark TIMEOUT/CANCELLED and unblock scheduled unique index for 06-10 trade_date.

3. **§7.3 — Timer-fired pipeline failed (Jun 11 22:35)**  
   Evidence: `UniqueViolationError` on `(CanonicalPriceMirror, 2026-06-11)`.  
   **Action:** Deduplicate mirror runner registration (single scheduled audit row per worker/date).

4. **§4.2 / §15 — Macro snapshot stale (06-10 vs expected 06-11)**  
   Evidence: `MAX(as_of_date)=2026-06-10`; prelive MACRO FAIL.  
   **Action:** Ensure macro timer fires post-close; run MacroIngestion + MacroRegime for 06-11.

5. **§6.5 / §8.6 — Nightly chain incomplete**  
   Evidence: no `daily_pipeline COMPLETED` for 06-10/11; sector still on 06-09.  
   **Action:** Restore ordered chain: macro → massive → mirror → daily_pipeline → sector.

6. **§15 — `prelive_check.py` exit 1**  
   Evidence: 6 FAIL checks (macro, gaps, calendar, stuck, heartbeats).  
   **Action:** Remediate items above until gate passes.

7. **§2.1 public schema** (launch-scope if public counts gate applies)  
   Evidence: `public.price_daily` ~1.2k rows/day vs ≈499 canonical.  
   **Action:** Treat public as legacy-only or narrow mirror scope; do not use public counts as canonical SLO.

---

## WARNINGS ACCEPTED BY DESIGN

- `rate_environment` / `dollar_regime` = `unknown` until ~21 macro snapshots for 30d deltas  
- `cpi_surprise` permanently NULL  
- DB default `search_path = theeyebeta, public` (deferred; app pin in `data_access/db.py`)  
- `public_ticker_map` 35,772 rows / 499 active (inert history)  
- Provider yfinance residual (3 names) on massive era days  
- ARGOS `sector_context` builder returns empty `data_gaps` but `as_of_date` lags prices  
- Host IO pressure elevated under 16 GB RAM workload  
- ISM PMI manual-entry WARN gaps (4 open WARN)

---

## NOT-DEPLOYED PHASES

- **Prompt 3:** `--allow-universe-sync` guard (not in code)  
- **Prompts 4–5:** `./theeye canonical {status,prelive}` CLI surface  
- **Prompt 8 / Supabase v2:** timer not loaded; no shadow reports in `reports/`  
- **Phase B intraday:** schema yes, **0 bars**; worker failing  
- **OOM correlation (§12.3):** audit blocked by journal latency

---

**VERDICT: NO-GO — 6 launch blockers listed above.**
