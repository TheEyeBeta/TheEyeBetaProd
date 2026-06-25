# Advisor data takeover — prod cutover

Replaces TheEyeBetaLocal engine output for AI-Financial-Advisor with Prod workers.

## Workers

| Worker | Unit | Purpose |
|---|---|---|
| `workers.latest_snapshot_worker` | `theeye-latest-snapshot.timer` | Upserts `theeyebeta.latest_snapshots` from canonical ingest tables (feeds DataAPI `:7000`) |
| `workers.supabase_sync_worker` | `theeye-supabase-sync.timer` | Publishes `latest_snapshots` → Supabase `stock_snapshots` (Advisor default path) |

## Local validation

```bash
uv run python -m workers.latest_snapshot_worker --dry-run
uv run python -m workers.latest_snapshot_worker
uv run python -m workers.supabase_sync_worker --shadow

psql "$DATABASE_URL" -c \
  "SELECT COUNT(*), MAX(updated_at) FROM theeyebeta.latest_snapshots;"
```

## Prod cutover (requires explicit operator approval)

1. Ensure `.env.theeye-latest-snapshot` and `.env.theeye-supabase-sync` provide `DATABASE_URL` / `MACRO_DATABASE_URL` and Supabase keys.
2. Install systemd units from `deploy/systemd/`:
   - `theeye-latest-snapshot.{service,timer}`
   - `theeye-supabase-sync.{service,timer}` (updated schedule)
3. Enable timers:
   ```bash
   systemctl --user enable --now theeye-latest-snapshot.timer
   systemctl --user enable --now theeye-supabase-sync.timer
   ```
4. Run **3 consecutive shadow days** for Supabase sync when validating a change:
   `uv run python -m workers.supabase_sync_worker --shadow`
   Review reports in `reports/supabase_shadow_YYYY-MM-DD.md`.
5. Production systemd unit runs **`--live`** (writes to Supabase). For manual shadow:
   `uv run python -m workers.supabase_sync_worker --shadow`
6. Verify:
   - DataAPI: `GET /api/v1/context?ticker=AAPL` returns fresh `last_price`
   - Supabase: `stock_snapshots.synced_at` advances on timer cadence
   - AI-Financial-Advisor Profile → data source `dataapi` shows live context

## Known MVP limitations

- `theeyebeta.market_news` is not refreshed by Prod news ingest (`news_articles` is separate). DataAPI news context may be stale until a follow-up bridge is added.
- Supabase `public.news` sync is not implemented in this MVP (snapshots only).

## Rollback

- Disable timers: `systemctl --user disable --now theeye-latest-snapshot.timer theeye-supabase-sync.timer`
- Re-enable Local engine only from the `TheEyeBetaLocal` tree if required (not recommended on prod host; units are masked).
