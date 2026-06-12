# Universe expansion runbook (499 → 4,000+ names, 5y history)

**Status:** written, not executed. **Host:** 16 GB RAM, ~118 GB DB, compressed `prices_daily` chunks.

## 1. Universe selection

- Source: top-N by dollar-volume from recent Massive grouped-daily ∪ existing 499.
- Exclusions (operator choice): ADR, OTC, penny — report counts before window.
- Seed file: `db/reference/universe_v1.txt` (curated; never auto-sync from `public.tickers`).

## 2. instruments + public_ticker_map

- Idempotent `INSERT` instruments from verified symbol list only.
- Map rows **only** from exact symbol matches; use `scripts/expand_universe.py --dry-run` first.
- `--allow-universe-sync` required on any copy script (see `TheEyeBetaLocal/scripts/copy_public_to_theeyebeta.py`).

## 3. Chunk plan (compressed hypertable)

```sql
SELECT chunk_name, range_start, range_end, is_compressed,
       pg_size_pretty(pg_total_relation_size(format('%I.%I', chunk_schema, chunk_name)::regclass)) AS size
  FROM timescaledb_information.chunks
 WHERE hypertable_schema = 'theeyebeta' AND hypertable_name = 'prices_daily'
   AND range_start >= now() - interval '5 years'
 ORDER BY range_start;
```

Per chunk: `decompress_chunk` → batch upsert (de-duped) → `recompress_chunk` → `ANALYZE`.

**Disk headroom:** estimate decompressed size ≈ 3–5× compressed per chunk; on 118 GB DB,
run **one chunk at a time** if free space < 30 GB. Operator must `df -h` before window.

## 4. Throughput (June 2026 reference)

- ~499 names × 6 days ≈ 19 min → ~1.4k rows/min.
- 4,000 × 1,260 trading days ≈ 5M rows → **~60 h** naive; parallel chunk windows on weekend only.

## 5. Derived data

- `theeyebeta_indicator_worker --from/--to` in chunks ≤100 instruments.
- `sector_aggregation_worker` recompute per day.
- Update `prelive_check.py` coverage denominators after expansion.

## 6. Checkpoint + rollback

- Table: `theeyebeta.backfill_progress` (chunk, status, started, finished).
- Failed chunk: recompress untouched; resume with `scripts/backfill_5y.py --resume`.

## 7. Execution (operator present)

```bash
uv run python scripts/expand_universe.py --dry-run
uv run python scripts/backfill_5y.py --dry-run
# window:
uv run python scripts/expand_universe.py --apply
uv run python scripts/backfill_5y.py --apply --resume
```

Daily chain timers **stay enabled**; verify newest chunk stays uncompressed for nightly writes.
