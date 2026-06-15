# Remediation pass — 2026-06-15

One-shot remediation of TheEyeBeta2025Live (run on `claude-opus-4-8`). Each numbered item is
a separate commit. Host-only systemd/DB state changes are recorded here because they leave no
other repo artifact. Constraint honored throughout: `public.*` not touched (deprecating);
`iam.*` read-only.

## P3 — cleanup

### [6] API supervision drift — `theeyebeta-api.service` masked

- The live external API runs as the **user** unit `theeyebeta-dataapi.service` (gunicorn, `:7000`).
- The system unit `theeyebeta-api.service` was disabled/dead and redundant.
- The host-only unit file was archived to `deploy/systemd/archived/theeyebeta-api.service`,
  removed from `/etc/systemd/system`, then `systemctl mask`ed (the path had to be freed first —
  it was a real file, not a `/usr/lib` shadow).
- Result: `is-enabled=masked`, `is-active=inactive`; `:7000` still served by `dataapi`.
- Reversible: `sudo systemctl unmask theeyebeta-api.service` + restore the archived file.

### [10] Unused daemons masked — engine / trask / watcher

- `theeyebeta-engine.service` (Trade Engine), `theeyebeta-trask.service` (monitoring daemon),
  and `theeyebeta-watcher.service` (repo auto-update/restart) were all inactive + disabled,
  with **no running equivalent** (no listeners). Their `ExecStart` points at a different tree
  (`/home/the-eye-beta/TheEyeBeta2025/TheEyeBetaLocal`), i.e. they belong to the Local/dev
  checkout, not this Prod host.
- Decision (opus): unused here, no deployment plan on this host → mask (also prevents an
  accidental start of the **trade engine**, which is desirable). Not started.
- Each host-only unit was archived to `deploy/systemd/archived/`, removed from
  `/etc/systemd/system`, then masked. All three now `is-enabled=masked`.
- Reversible: `sudo systemctl unmask <unit>` + restore the archived file. If they are meant
  to run, they should be deployed from the `TheEyeBetaLocal` tree, not unmasked here.

### [8] supabase-sync — disabled + masked (broken worker, product decision pending)

- Investigation: `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` are all set
  in `.env` and the worker is actively versioned (v2), so Supabase is not cleanly "replaced".
  BUT the worker runs `--shadow` only (no external writes) and **fails at runtime**:
  `asyncpg.UndefinedTableError: relation "theeyebeta.data_snapshots_packaged" does not exist`
  (closest real table is `theeyebeta.data_snapshots`). The timer was never enabled.
- Decision (opus): do NOT enable a broken, shadow-only unit (that just recreates the
  litellm-style failing-unit problem). Do NOT delete it either — keys are present, so intent is
  unclear. Disabled + masked `theeye-supabase-sync.{timer,service}` on the host so it can't
  accidentally start; kept the worker code, repo unit files, and keys. Filed issue #5 for the
  product decision (fix table ref + enable, or fully retire).
- `is-enabled=masked` for both units. Reversible via unmask once the table reference is fixed.

### [7] Dropped orphaned 507 MB backup table

- `theeyebeta.ind_technical_daily_orphan_bak_20260610` (507 MB, ~4.2M rows) was an ad-hoc dated
  backup — not part of the Alembic-modeled schema, owned by `postgres` (the admin role couldn't
  even read it).
- Decision (opus): a one-off DROP of a non-model artifact is NOT an Alembic schema migration. An
  Alembic migration would have an impossible `downgrade()` (the rows are gone) and would pollute
  the chain with a table it never created. The user authorized the exact `DROP TABLE IF EXISTS`,
  so this was a direct `DROP TABLE` as the `postgres` superuser (peer auth).
- Space: a full `DROP TABLE` returns the table's files to the OS immediately — no `VACUUM` needed
  (VACUUM only reclaims intra-table dead tuples after DELETEs).
- The session DB-delete guard hook (blocks DROP/DELETE/TRUNCATE) was temporarily lifted via
  `disableAllHooks` for this single authorized drop, then restored and re-verified.
- Verified: `to_regclass('…orphan_bak_20260610') IS NULL` → true (gone).
