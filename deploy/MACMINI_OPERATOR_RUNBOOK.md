# Mac Mini Operator Runbook — Prod-Only (theeyebeta.*)

Run on the Mac mini as user `the-eye-beta`. All operations use **TheEyeBetaProd**
and the **`tb` CLI** — no `TheEyeBetaLocal` or `./theeye` dependencies.

Repo: `/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd`

---

## 0. Pre-flight

```bash
cd /home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd
uv sync
uv run tb --install-completion   # optional: bash/zsh tab completion
uv run tb status
uv run tb meta doctor
uv run tb prelive
uv run python scripts/check_no_public_refs.py
```

Full command tree: [docs/CLI_REFERENCE.md](../docs/CLI_REFERENCE.md)

---

## 1. Apply migrations

```bash
cd /home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd
uv run tb db migrate
# or: make db-migrate
```

Verify:

```bash
sudo -u postgres psql -d TheEyeBeta2025Live -c \
  "SELECT version_num FROM theeyebeta.alembic_version ORDER BY version_num DESC LIMIT 5;"
```

Expected head includes `0024_public_ticker_map` (or later).

---

## 2. Install / enable systemd timers

```bash
cd /home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd
sudo ./deploy/install_systemd_units.sh
sudo systemctl daemon-reload

# Fixed-income worker environment:
# /home/the-eye-beta/TheEyeBeta2025/TheEyeBetaProd/.env.theeye-fixed-income
# must contain DATABASE_URL or MACRO_DATABASE_URL, plus FRED_API_KEY.

sudo systemctl enable --now theeye-macro.timer
sudo systemctl enable --now theeye-fixed-income.timer
sudo systemctl enable --now theeye-massive-ingest.timer
sudo systemctl enable --now theeye-daily-pipeline.timer
sudo systemctl enable --now theeye-gap-sentinel.timer
sudo systemctl enable --now theeye-sector.timer
sudo systemctl enable --now theeye-market-cap.timer
sudo systemctl enable --now theeye-intraday-ingest.timer
sudo systemctl enable --now theeye-backup.timer

systemctl list-timers 'theeye-*'
```

---

## 3. Universe tiers

```bash
# EOD tier (~11k) — sets instruments.active
uv run tb universe sync --tier eod --apply

# Intraday tier file only (>= $500M)
uv run tb universe sync --tier intraday
```

---

## 4. Smoke tests

```bash
uv run tb workers run massive-ingest --dry-run
uv run python -m workers.fixed_income.pipeline_worker --dry-run
uv run tb workers run fixed-income --dry-run
systemctl cat theeye-fixed-income.timer
uv run tb workers run intraday-ingest --dry-run --force --date 2026-06-12
uv run tb workers run indicator-compute --dry-run --date 2026-06-12
uv run tb trask status
uv run tb prelive
```

During US market hours:

```bash
uv run tb workers run intraday-ingest --force
```

---

## 5. Daily chain (automatic)

| UTC (approx) | Timer | Action |
|--------------|-------|--------|
| 13:35–20:05 Mon–Fri | intraday | 15m bars (>= $500M) |
| 21:00 | market-cap | Cap fetch + EOD universe sync |
| 21:45 | fixed-income | Treasury/credit curve metrics + signals |
| ~22:31 | massive-ingest | EOD prices (full active universe) |
| ~22:36 | daily-pipeline | Indicator compute + validation |
| morning | gap-sentinel | Freshness + stuck-run checks |

---

## 6. Trask / worker audit

All worker runs write to `theeyebeta.worker_runs`, `theeyebeta.worker_heartbeats`,
and `theeyebeta.trask_components`.

```bash
uv run tb trask workers
uv run tb trask status
```

```sql
SELECT worker_name, trade_date, status, ended_at
  FROM theeyebeta.worker_runs
 ORDER BY started_at DESC LIMIT 20;
```

Fixed-income verification:

```sql
SELECT date, bond_environment_score, bond_environment_label
  FROM theeyebeta.fixed_income_curve_metrics
 ORDER BY date DESC
 LIMIT 5;
```

---

## 7. June 30 deprecation

- Revoke `tb_app` write grants on `public.*` (postgres): `psql -f scripts/revoke_public_writes.sql`
- Delete `scripts/mirror_canonical_prices_to_public.py`
- Archive `TheEyeBetaLocal` checkout on this host
