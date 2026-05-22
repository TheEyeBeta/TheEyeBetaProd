---
paths: ["db/migrations/**"]
---

# SQL / Migration Rules

## Migration Tool

- **Alembic only.** No hand-edited SQL files in `db/migrations/`; every schema change goes
  through a versioned migration script.
- **One migration per logical module** as defined in `docs/architecture.md §4.2`.
  Do not bundle unrelated table changes in a single migration.
- Every migration must implement both `upgrade()` and `downgrade()` — empty `downgrade` is
  only permitted for irreversible operations (e.g. dropping a column with live data), and must
  include a comment explaining why.

## Schema Conventions

- **Foreign keys:** all FK constraints declared with `ON DELETE RESTRICT` unless a different
  policy is explicitly justified in a code comment and approved via ADR.
- **Timestamps:** all timestamp columns use `TIMESTAMPTZ NOT NULL`. No `TIMESTAMP WITHOUT
  TIME ZONE`, no nullable timestamps (use a sentinel value or a separate boolean instead).
- **Primary keys:** prefer `UUID` (generated server-side with `gen_random_uuid()`) for
  entities that will be referenced externally. Use `BIGSERIAL` only for internal high-volume
  append-only tables (e.g. tick data).
- **Naming:** `snake_case` for all identifiers. Table names: plural noun (`orders`, `users`).
  Junction tables: `<table_a>_<table_b>` alphabetically.

## TimescaleDB

- Time-series tables must call `create_hypertable()` **after** the `CREATE TABLE` statement
  in the same migration, not in a separate migration:
  ```python
  op.execute("SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);")
  ```
- Chunk interval defaults to 1 day for tick/event tables; 1 week for aggregate tables.
  Override by passing `chunk_time_interval` explicitly.
- Never call `create_hypertable()` on a table that already contains rows — backfill in a
  separate, data-only migration with explicit user confirmation.

## Audit Log Policy

- The `audit_log` table is **append-only**. No migration may:
  - Add `UPDATE` or `DELETE` grants on `audit_log` to any role.
  - `DROP` or `TRUNCATE` `audit_log`.
  - Remove columns from `audit_log`.
- Additions (new columns, new indexes) are permitted.
- Any attempt to modify existing `audit_log` rows is a compliance violation.

## Linting

- All `.sql` files linted with `sqlfluff --dialect postgres`.
- All Alembic `op.execute()` strings must be linted manually — add a `# sqlfluff: disable`
  comment only with justification.
- `make lint-sql` must pass in CI.
