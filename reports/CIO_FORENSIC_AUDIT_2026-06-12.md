# CIO FORENSIC AUDIT — Data Pipeline, 50/10 Standard

**Audit window:** 2026-06-12 22:40 UTC+1 → 2026-06-13 (overnight remediation)
**Auditor:** Claude (CIO forensic mandate — audit, fix, validate)
**Scope:** TheEyeBetaProd + TheEyeBetaLocal, DB `TheEyeBeta2025Live` (PostgreSQL 16.14 + TimescaleDB)
**Baseline:** `reports/GRAND_AUDIT_2026-06-12.md` (read-only, NO-GO, 6 launch blockers)
**This audit:** read/write — root causes fixed in code, data healed, gate re-run

---

## 1. EXECUTIVE SUMMARY

The platform's canonical data spine (Massive → `theeyebeta.prices_daily` → mirror →
legacy compute → canonical indicators → sector aggregates) was broken at five
distinct points. None were data-corruption bugs — prices in both schemas are
clean, duplicate-free, and cross-schema consistent to 6 decimal places. All five
were **orchestration and architecture defects** that made the nightly chain
unable to complete:

1. **PIPE-001 (CRITICAL)** — duplicate-key crash in scheduled audit registration
   killed the 21:35 daily-pipeline unit two nights running (Jun 11, Jun 12).
2. **PIPE-002 (CRITICAL)** — the audited `daily_pipeline` runner invoked a
   multi-hour yfinance universe sweep (`force_update=True`, 1,790 tickers)
   against a 90-minute systemd timeout. It had **never completed once**.
3. **PIPE-003 (CRITICAL)** — the runner's compute engine
   (`core.pipeline.daily_pipeline`) computes **SMA/EMA only**; the full-column
   engine the retired daemon used (`etl.jobs.compute_technical_daily`: RSI,
   MACD, ROC, crosses) was dropped from the chain when the daemon was retired.
4. **PIPE-004 (CRITICAL)** — the canonical indicator worker was a **skeleton**
   (`records_written=0` placeholder), so nothing scheduled ever wrote
   `theeyebeta.ind_technical_daily`; sector aggregation then failed its
   precondition every night.
5. **PIPE-005 (HIGH)** — installed systemd units drifted from the repo: the
   intraday unit passed `--run-type scheduled` which the worker's argparse
   rejected (exit 2 every 15 minutes, all day), and the massive-ingest unit
   silently dropped the indicator/sector steps present in the repo unit.

All five are fixed in code, the chain re-run for 2026-06-10 → 2026-06-12, and
the formal gate (`scripts/prelive_check.py`) re-validated. See §6.

---

## 2. DEFECT REGISTER (evidence-backed)

### PIPE-001 — Scheduled re-registration crashes the nightly unit
- **Severity:** CRITICAL — root cause of both consecutive nightly chain failures
- **File:** `workers/base_worker.py::_start_run`
- **Mechanism:** partial unique index
  `audit_worker_runs_scheduled_unique_idx (worker_name, trade_date) WHERE run_type='scheduled'`
  + CLI defaults of `--run-type scheduled` on the mirror/runner/sector workers.
  Any morning catch-up run without flags registered a *scheduled* row for the
  current day; the evening timer then hit `asyncpg.exceptions.UniqueViolationError`
  inside `_start_run`, the first `ExecStart` of the oneshot unit exited 1, and
  systemd never ran the remaining `ExecStart` steps.
- **Evidence:**
  - `journalctl -u theeye-daily-pipeline` Jun 12 22:35:22:
    `UniqueViolationError: ... Key (worker_name, trade_date)=(CanonicalPriceMirror, 2026-06-12) already exists`
  - Identical failure Jun 11 22:35 for `(CanonicalPriceMirror, 2026-06-11)`
    (GRAND_AUDIT §7.3).
  - Poisoning rows: run 99666 (scheduled, 03:25, 0 records) and run 99464
    (scheduled, Jun 11 01:50, 0 records) — both early-morning catch-ups that
    defaulted to `scheduled`.
- **Fix:** `_start_run` now catches `UniqueViolationError` for scheduled runs
  and re-registers as `recovery` (append-only audit preserved, unit keeps
  going); CLI defaults flipped to `manual` on mirror, runner, indicator,
  intraday workers (systemd passes `--run-type scheduled` explicitly).
- **Live validation:** run 99789 — the 23:35 intraday timer hit the existing
  scheduled row from 15:50, fell back to `recovery`, COMPLETED, unit exit 0.

### PIPE-002 — Nightly pipeline architecturally unable to finish
- **Severity:** CRITICAL
- **Files:** `workers/daily_pipeline_runner.py` (hardcoded
  `mode="full", force_update=True`), `deploy/systemd/theeye-daily-pipeline.service`
  (`TimeoutStartSec=5400`)
- **Mechanism:** full mode refetches all ~1,790 active public tickers via
  yfinance (heavily throttled), then recomputes the full indicator series per
  ticker via row-by-row ORM upserts (~1,600 rows × 1,790 tickers). Measured:
  >6.8h without completing. systemd kills the unit at 90 minutes.
- **Evidence:** `audit_worker_runs` contains **zero** COMPLETED rows for
  `worker_name='daily_pipeline'` in its entire history; manual run 99781
  cancelled after 6.8h still in the price step; cancelled sweep 99791
  (compute_only) was projected ~5h from observed throughput (~22 tickers/min).
- **Fix:** runner gains `--engine etl` (default): runs
  `etl.jobs.compute_technical_daily(target_date)` — single-date, full-column,
  one upsert per ticker, minutes not hours. The legacy sweep remains available
  via `--engine legacy --mode {full,ingest_only,compute_only}`.

### PIPE-003 — Wrong indicator engine (SMA/EMA-only) wired into the chain
- **Severity:** CRITICAL (silent data-quality regression)
- **Mechanism:** the retired daemon
  (`engine/workers/daily_pipeline_worker.py::_run_sync_pipeline`) chained
  `etl.jobs.compute_technical_daily` (+ risk/valuation/quality jobs). The
  systemd-era runner instead calls `core.pipeline.daily_pipeline`, whose
  `compute_indicators` produces **only sma_10/50/200 + ema_10/50/200** —
  `rsi_14`, `macd*`, `roc_*`, crosses are written as NULL.
- **Evidence:** `public.ind_technical_daily` 2026-06-10: 1,628 rows, **0** with
  `rsi_14` (all from the core-pipeline path); 2026-06-11: 1,045/2,041 with
  `rsi_14` (the full-column subset written by the ETL engine during the heal
  campaign). Sector aggregation consumes `median_rsi_14` — NULL inputs would
  have silently degraded sector quality metrics.
- **Fix:** ETL engine is now the runner default (PIPE-002 fix);
  the SMA/EMA-only rows for 06-10 were overwritten by the full-column ETL
  recompute during remediation.

### PIPE-004 — Canonical indicator worker was a skeleton
- **Severity:** CRITICAL
- **File:** `workers/theeyebeta_indicator_worker.py`
- **Mechanism:** `execute()` counted price rows and returned
  `records_written=0` with metadata
  `"status": "skeleton — wire compute kernel in Phase C validation pass"`.
  COMPLETED-with-zero-writes audit rows masked the no-op. Nothing scheduled
  ever wrote `theeyebeta.ind_technical_daily`; `SectorAggregationWorker`
  then failed `Precondition failed: theeyebeta.ind_technical_daily has no rows`
  every night (runs 99780, 99787).
- **Evidence:** worker source (pre-fix); `theeyebeta.ind_technical_daily`
  frozen at 2026-06-09 while canonical prices advanced to 2026-06-12.
- **Fix:** implemented the Phase-B bridge sync: active-universe slice of
  `public.ind_technical_daily` → `theeyebeta.ind_technical_daily`
  (`ON CONFLICT (instrument_id, date) DO UPDATE`, `DISTINCT ON` guard, loud
  failure when upstream rows are missing). Wired as ExecStart #3 of the
  daily-pipeline unit. Native Phase-C compute remains the documented follow-up.

### PIPE-005 — Deployed systemd units drifted from the repo
- **Severity:** HIGH
- **Evidence (diff repo vs `/etc/systemd/system`):**
  - `theeye-intraday-ingest.service`: installed unit passes
    `--run-type scheduled`; worker argparse rejected it →
    `status=2/INVALIDARGUMENT` every 15 minutes from 16:05 to 23:20 (journal +
    `reports/intraday-ingest-journal-2026-06-12.txt`).
  - `theeye-massive-ingest.service`: repo unit had indicator + sector
    ExecStarts; installed unit had neither — and the repo ordering was itself
    wrong (indicator sync at 21:30 before the 21:35 mirror/compute can feed it).
  - `theeye-supabase-sync.{service,timer}`: in repo, never installed
    (known NOT-DEPLOYED phase).
- **Fix:** repo units redefined as the single source of truth with correct
  ordering (massive 21:30 → [mirror → ETL compute → indicator sync] 21:35 →
  sector 22:05); intraday worker now accepts `--run-type`;
  `deploy/install_systemd_units.sh` added (idempotent, needs sudo).

### PIPE-006 — Intraday worker: one slow symbol aborted the run
- **Severity:** MEDIUM
- **File:** `workers/intraday_ingestion_worker.py`
- **Evidence:** run 99774 FAILED with `httpx.ReadTimeout` at 15:51 after 42s;
  0 bars ever ingested into `theeyebeta.prices_intraday`.
- **Fix:** per-symbol bounded retry (2 retries, linear backoff) and
  swallow-with-log on persistent HTTP errors — a symbol-level failure now costs
  coverage, not the run. Coverage warnings already existed
  (`COVERAGE_WARN_THRESHOLD=0.90`).
- **Residual:** worker design re-downloads the full day per symbol per tick
  (499 sequential calls/15 min) — wasteful; see §7 recommendations.

### PIPE-007 — Stuck STARTED runs from killed processes
- **Severity:** MEDIUM (gate-blocking when present)
- **Evidence:** run 99664 (recovery, orphaned 03:15), run 99781 (manual,
  launched 16:53, still in the yfinance price step 6.8h later).
- **Fix applied tonight:** processes terminated, rows closed out as FAILED with
  explanatory `error_message`; the >2h stuck-run sentinel already detects these
  (`gap_sentinel_worker.check_stuck_worker_runs`).
- **Recommended hardening:** see §7 (systemd `RuntimeMaxSec`, watchdog sweep).

### PIPE-008 — ETL upsert is not concurrency-safe (discovered during remediation)
- **Severity:** MEDIUM
- **File:** `TheEyeBetaLocal/services/etl/src/etl/jobs/compute_technical_daily.py`
- **Mechanism:** `session.merge()` is SELECT-then-INSERT; two concurrent runs
  for the same date race between the SELECT and the final single commit.
- **Evidence:** run 99809 (a second agent session re-running 06-11 in parallel)
  FAILED with `psycopg.errors.UniqueViolation ... (ticker_id, date)=(1488, 2026-06-11)`
  against rows committed seconds earlier by run 99806. The poisoned transaction
  rolled back atomically — zero partial writes (good), whole run lost (bad).
- **Recommendation:** per-row `INSERT ... ON CONFLICT (ticker_id, date) DO UPDATE`
  or a `pg_advisory_xact_lock(hash('compute_technical_daily', date))` guard.

### PIPE-009 — `make test` could not import the workers package
- **Severity:** MEDIUM (test-blind spot)
- **Evidence:** `[tool.pytest.ini_options]` had no `pythonpath`; `make test`
  failed collection with `ModuleNotFoundError: No module named 'workers'` —
  every worker test was invisible to the official target (docs worked around it
  with `PYTHONPATH=.`).
- **Fix:** `pythonpath = ["."]` added to `pyproject.toml`. Side effect: 12
  pre-existing `services/` test failures + 4 errors (Pydantic 2.13
  `extra_forbidden` strictness) are now *visible*; they are outside the data
  pipeline and left for the service owners (§7).

### DATA-001 — yfinance backfill rows violate OHLC invariants
- **Severity:** LOW (documented, not mutated)
- **Evidence:** 14 canonical + 17 public rows dated 2026-06-09, all
  `source='yfinance_backfill_prices'`, where `open` sits up to $0.88 outside
  `[low, high]` (e.g., WAT open 367.94 vs low 368.82). Known yfinance artifact
  (open from raw feed, range from adjusted intraday). Close-based indicators
  are unaffected; both schemas carry identical values so parity holds.
- **Recommendation:** re-pull 2026-06-09 from Massive for the 14 names and
  update both schemas in one transaction; add the OHLC check to the gap
  sentinel; add a CHECK-style validation to future backfill scripts (the
  massive worker already validates bars).

### Minor / accepted findings
- **BK missing 2026-06-12** in canonical prices (498/499): both providers
  lacked the bar (massive=496, yfinance=2, `missing_symbols=["BK"]`,
  coverage 0.998, threshold 0.95). Provider-side; backfill when available.
- `.env` plaintext secrets + world-readable — violates the repo's own
  sops/age policy (Rule 03). Out of tonight's scope; flagged for rotation +
  sops migration (§7).
- `public_ticker_map` bloat (35,772 rows / 499 active) — inert, accepted.
- ISM PMI manual-entry WARN gaps (8 open WARN rows) — by design until manual
  entry lands.
- `momentum_rank_12_1` is not produced by any current engine (NULL across
  06-11 population) — column is dead until Phase C; documented.

---

## 3. WHAT WAS HEALED (data remediation log)

| Step | Action | Result |
|------|--------|--------|
| 1 | Marked stuck run 99781 FAILED (`OperatorCancelled`), killed 6.8h yfinance sweep | stuck-runs gate clear |
| 2 | Mirror 2026-06-12 → `public.price_daily` (`--run-type recovery`, run 99790) | 498/499 written, coverage 0.998 (BK provider-missing) |
| 3 | Cancelled doomed compute_only sweep (99791), marked FAILED with rationale | — |
| 4 | ETL-engine pipeline runs (`--engine etl --run-type recovery`) | 06-10: run 99803, **760s**, 10,036 full-column rows; 06-11: run 99806, ~210s, 10,043 rows; 06-12: run 99810, **116s**, 494 rows — vs. the legacy sweep that never finished in 6.8h |
| 5 | Canonical indicator bridge sync (fixed worker, first live runs) | 06-10: 493 rows (cov 0.988); 06-11: 494 (cov 0.99); 06-12: 494 (cov 0.99) |
| 6 | Sector aggregation | 12 sectors/day for 06-10 (SPY proxy), 06-11 (SPY proxy), 06-12 (live ^GSPC return) |
| 7 | Resolved CRITICAL gaps 162501/162502 citing completing run ids | open CRITICAL gaps = 0 |
| 8 | AAPL continuity verified | sma_50 06-09→06-11: 283.0454 → 283.9444 → 284.7778 (smooth, full columns), matches daemon-era series methodology |

---

## 4. PRODUCTION READINESS SCORECARD

| Capability | Status | Evidence |
|------------|--------|----------|
| Fetch works (canonical) | **YES** | Massive ingest COMPLETED 06-10/11/12; coverage 498-499/499; provider fallback (yfinance) engaged automatically |
| Parse + validate works | **YES** | massive worker validates bars, records `missing_symbols` + `coverage_outcome`; intraday `validate_bar` rejects malformed OHLC |
| Insert works | **YES** | canonical 06-12: 498 rows; cross-schema spot check 10/10 symbols rel-diff 0.00000 |
| Deduplicate works | **YES** | 0 duplicate (instrument, date) groups in 7d in both schemas; mirror `ON CONFLICT DO NOTHING`; sync `ON CONFLICT DO UPDATE` |
| Idempotent | **YES (proven)** | full 06-12 tail re-run: price/indicator/sector counts 498/494/12 before and after; mirror correctly wrote 0 |
| Complete | YES* | 499/499 on 06-11; 498/499 on 06-10/06-12 (BK provider-side); coverage gate ≥0.95 |
| Fresh | **YES** | latest canonical = expected trading day (06-12); macro snapshot 06-12; sector 06-12 |
| Scheduled | **YES** | 7 timers active; chain order fixed (21:20 macro → 21:30 massive → 21:35 mirror+ETL+sync → 22:05 sector); unit install pending one sudo command |
| Error handling | **YES** | dup-registration falls back to recovery (proven live, run 99789); intraday per-symbol retry; loud preconditions in sync/sector |
| Monitored | **YES** | gap sentinel (calendar, freshness, stuck-runs) + audit_worker_runs terminal states + heartbeats 5/5 fresh; alerting hook still recommended (§7) |
| Recoverable | **YES** | every worker supports `--date X --run-type recovery`; demonstrated for 3 dates |
| Auditable | **YES** | every run registered in append-only `audit_worker_runs` with metadata (rows before/after, coverage, engine); `audit_log` immutability intact — zero rows touched |
| Tested | **YES (pipeline scope)** | 54/54 unit tests in `tests/unit` incl. 12 new; `make test` import defect fixed |

\* BK 2026-06-12 missing at both providers — documented, backfill when published.

---

## 5. CODE CHANGES (all in TheEyeBetaProd)

| File | Change |
|------|--------|
| `workers/base_worker.py` | scheduled→recovery fallback on duplicate registration (PIPE-001) |
| `workers/daily_pipeline_runner.py` | `--engine etl\|legacy`, `--mode`, `--force-update`, default run-type `manual` (PIPE-002/003) |
| `workers/theeyebeta_indicator_worker.py` | real bridge sync replaces skeleton (PIPE-004) |
| `workers/intraday_ingestion_worker.py` | `--run-type` arg; per-symbol retry/tolerance (PIPE-005/006) |
| `scripts/mirror_canonical_prices_to_public.py` | default run-type `manual` (PIPE-001) |
| `deploy/systemd/theeye-daily-pipeline.service` | mirror → ETL pipeline → indicator sync |
| `deploy/systemd/theeye-massive-ingest.service` | single-purpose (massive only), timeout 1800 |
| `deploy/systemd/theeye-intraday-ingest.service` | `--once --run-type scheduled` |
| `deploy/install_systemd_units.sh` | new idempotent unit installer (sudo) |
| `tests/unit/test_base_worker.py` | new — fallback semantics |
| `tests/unit/test_theeyebeta_indicator_worker.py` | new — sync SQL, preconditions, dry-run |
| `tests/unit/test_daily_pipeline_runner.py` | new — engine dispatch, zero-row failure, trading-day gate |

Also: `pyproject.toml` gained `pythonpath = ["."]` (PIPE-009).

Test suite: `tests/unit` 54/54 passed (12 new tests for the fixes). Repo-wide:
161 passed, 12 failed + 4 errors — all pre-existing `services/` Pydantic-2.13
strictness issues, newly *visible* because collection now works; outside
pipeline scope. Lint: ruff clean on every touched file (`make lint` still fails
on 289 pre-existing issues in untouched files — §7).

---

## 6. FORMAL GATE — `scripts/prelive_check.py` (2026-06-13 01:18 local)

```
 1  MIGRATION HEADS            PASS  public=20260610_01, theeyebeta=0013_prices_intraday
 2  CANONICAL PRICE FRESHNESS  PASS  latest=2026-06-12 rows=498 expected=2026-06-12 min_rows=474
 3  MACRO FRESHNESS+SANITY     PASS  snapshot=2026-06-12, labels_known=3/5
 4  GAPS                       PASS  open CRITICAL gaps=0
 5  CALENDAR SENTINEL          WARN  pipeline missing=7 (untriaged=none); massive missing=none
 6  STUCK RUNS                 PASS  none
 7  CIRCUIT BREAKERS           PASS  open=0
 8  CROSS-SCHEMA SPOT CHECK    PASS  10 compared on 2026-06-12; worst rel diff 0.00000
 9  ARGOS DRY-RUN              WARN  macro 30d-delta gaps only (need ~21 snapshots; by design)
10  HEARTBEATS                 PASS  5/5 fresh (<26h)
11  DISK                       PASS  64.9% free
12  BACKUP RECENCY             PASS  10.8GiB, 22.7h old, theeye-backup.timer active

RESULT: 12 checks, 0 FAIL, 2 WARN          (morning baseline: 6 FAIL — NO-GO)
```

Exit code 0. Both WARNs are accepted-by-design (triaged historical pipeline
days; macro delta features awaiting snapshot history). The `sector_context`
gap from the morning audit is gone.

**VERDICT: GO** — contingent on the one operator command in §7
(`sudo deploy/install_systemd_units.sh`) before Monday's 21:20 UTC chain.

---

## 7. NEXT STEPS

**Operator action required (one command):**
```bash
sudo deploy/install_systemd_units.sh
```
(refreshes `theeye-daily-pipeline` / `theeye-massive-ingest` /
`theeye-intraday-ingest` units; sudo unavailable to the agent.)

**This week**
- Rotate every credential in `.env` and complete the sops/age migration —
  plaintext API keys, SMTP, and Supabase service-role keys violate Rule 03.
- **Single-operator discipline:** a second agent session was still active
  during this audit and re-ran the same heal steps concurrently (caused the
  PIPE-008 collision, run 99809). End stale sessions before prod operations,
  or add the advisory-lock guard so concurrent runs serialize.
- Triage the 12 pre-existing `services/` test failures (Pydantic 2.13
  `extra_forbidden`) and the 289 repo-wide ruff findings so `make lint` /
  `make test` can gate CI honestly.
- Add `RuntimeMaxSec=` to long-running units and a stuck-run auto-sweep
  (gap sentinel already detects; add remediation).
- Backfill BK 2026-06-12 when a provider publishes the bar; add a
  single-symbol backfill flag to the massive worker.
- Install supabase-sync units or formally descope Phase 8.

**This month**
- Phase C: native canonical indicator compute from `theeyebeta.prices_daily`
  (removes the public bridge + mirror entirely); add `compute_risk_daily`
  back into the nightly chain (`ind_risk_daily` is still legacy-fed).
- Intraday: batch endpoint or per-bucket grouped fetch instead of 499
  full-day downloads per tick; consider concurrency with a semaphore.
- Alerting: page on `theeye-*` unit failure (systemd `OnFailure=` →
  alertmanager hook) — tonight's failures were silent.

**This quarter**
- Retire the legacy public universe or shrink it to the canonical 499 + indices.
- Replace per-ticker ORM loops in remaining ETL jobs with set-based SQL.
