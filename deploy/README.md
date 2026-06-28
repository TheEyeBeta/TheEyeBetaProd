# Deployment Helpers

All runtime paths use **TheEyeBetaProd** + `theeyebeta.*` only. Operator CLI:
`uv run tb` — see [docs/CLI_REFERENCE.md](../docs/CLI_REFERENCE.md).

```bash
uv sync
uv run tb status
uv run tb prelive
uv run tb trask status
uv run tb workers list
```

Install all units: `sudo ./deploy/install_systemd_units.sh`

See [MACMINI_OPERATOR_RUNBOOK.md](MACMINI_OPERATOR_RUNBOOK.md) for the full cutover guide.

## Massive Canonical Price Ingestion Timer

Install and enable the canonical price ingestion timer (runs before the legacy
public pipeline at 21:35 UTC):

```bash
sudo cp deploy/systemd/theeye-massive-ingest.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-massive-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-massive-ingest.timer
systemctl list-timers theeye-massive-ingest.timer
```

Dry-run plan (no writes, no audit rows):

```bash
uv run python -m workers.massive_ingestion_worker --dry-run
```

## Macro Workers Timer

Install and enable the macro ingestion/regime timer:

```bash
sudo cp deploy/systemd/theeye-macro.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-macro.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-macro.timer
systemctl list-timers theeye-macro.timer
```

Run manually:

```bash
uv run python -m workers.macro_pipeline --run-type manual
```

## Fixed-Income Regime Timer

Create `/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd/.env.theeye-fixed-income`
with `DATABASE_URL` or `MACRO_DATABASE_URL`, plus `FRED_API_KEY`.

Install and enable the fixed-income regime timer (runs after macro jobs at
21:45 UTC, Mon-Fri):

```bash
sudo cp deploy/systemd/theeye-fixed-income.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-fixed-income.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-fixed-income.timer
systemctl list-timers theeye-fixed-income.timer
systemctl cat theeye-fixed-income.timer
```

Dry-run / manual checks:

```bash
uv run python -m workers.fixed_income.pipeline_worker --dry-run
uv run tb workers run fixed-income --dry-run
```

## Daily Pipeline Timer

Install and enable the daily market-data pipeline timer:

```bash
sudo cp deploy/systemd/theeye-daily-pipeline.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-daily-pipeline.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-daily-pipeline.timer
systemctl list-timers theeye-daily-pipeline.timer
```

Run manually:

```bash
uv run tb workers run daily-pipeline --dry-run
uv run python -m workers.daily_pipeline_runner --run-type manual
```

Pipeline steps: `IndicatorComputeWorker` → `TheeyebetaIndicatorWorker` (validation).
No `public.*` mirror. No `TheEyeBetaLocal` ETL.

## Gap Sentinel Timer

Install and enable the morning gap sentinel:

```bash
sudo cp deploy/systemd/theeye-gap-sentinel.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-gap-sentinel.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-gap-sentinel.timer
systemctl list-timers theeye-gap-sentinel.timer
```

Run manually:

```bash
uv run python -m workers.gap_sentinel_worker --run-type manual
```

## Sector Aggregation Timer

Install and enable the per-sector daily aggregation (runs after the nightly
ingest + indicator sync at 22:05 UTC; the worker fails loudly if indicators
for the target date are absent):

```bash
sudo cp deploy/systemd/theeye-sector.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-sector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-sector.timer
systemctl list-timers theeye-sector.timer
```

Run manually / dry-run:

```bash
uv run python -m workers.sector_aggregation_worker --dry-run
uv run python -m workers.sector_aggregation_worker --date 2026-06-10 --run-type manual
```

## Nightly Database Backup Timer

Install and enable the nightly pg_dump backup (03:30 UTC, 14-day rotation in
`/home/the-eye-beta/backups`):

```bash
sudo cp deploy/systemd/theeye-backup.service /etc/systemd/system/
sudo cp deploy/systemd/theeye-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now theeye-backup.timer
systemctl list-timers theeye-backup.timer
```

Run manually:

```bash
scripts/backup_db.sh
```

## Pre-live Go/No-Go Harness

Read-only; exit 0 only with zero FAILs:

```bash
uv run tb prelive
uv run tb prelive --json
uv run python scripts/prelive_check.py
uv run python scripts/prelive_check.py --json
```

## Intraday 15m Timer (>= $500M tier)

```bash
sudo systemctl enable --now theeye-intraday-ingest.timer
uv run tb workers run intraday-ingest --dry-run --force
```

## Market Cap + EOD Universe Timer

```bash
sudo systemctl enable --now theeye-market-cap.timer
uv run tb universe sync --tier eod --apply
```

## Legacy Reference Check

```bash
uv run python scripts/check_no_public_refs.py
```

