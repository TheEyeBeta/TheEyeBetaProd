# Data Model

> See [architecture.md §4](architecture.md#4-data-model) for the migration-by-migration table.
> This file covers the schema mechanics; `docs/db-state-map.md` is the generated, point-in-time
> diagnostic (table sizes, row counts, role grants); `docs/db-engineer-SKILL.md` is the mandatory
> read before any DB-adjacent change.

## The Shared-Instance Reality

This repo's Alembic project owns **one schema: `theeyebeta`**. The same PostgreSQL instance also
hosts a `public` schema (96 GB, 69 tables, actively written by a separate, currently-unlocated
codebase — see `docs/db-state-map.md §9`) and an `iam` schema (service auth, owned elsewhere).
**Never assume an unqualified table name like `signals` or `exchanges` means the `theeyebeta`
version** — both schemas have tables with those exact names and incompatible column layouts (see
`docs/db-state-map.md §4` for the full diff). The two schemas have independent `alembic_version`
tables and must never be migrated together.

## PostgreSQL Extensions

Enabled via migration `0000_extensions`:

- `timescaledb` — hypertables, compression
- `vector` (pgvector) — HNSW ANN search on `news_embeddings` and `agent_memory`
- `pgcrypto` — `gen_random_uuid()` for primary keys (not `uuid-ossp`)
- `pg_stat_statements` — query performance monitoring

## Schema: `theeyebeta`

One schema, ~39 tables as of the last `db-state-map` scan, organized by domain rather than by
Postgres schema (an earlier draft of this doc described separate `market`/`orders`/`risk`/
`research`/`compliance` schemas — that design was never built; everything lives in `theeyebeta`).
See [architecture.md §4.1](architecture.md#41-the-theeyebeta-schema) for the full
migration → table mapping.

### `audit_log`

Append-only, hash-chained, monthly RANGE-partitioned (migration `0009`, hardened in `0029`/`0034`).
**No UPDATE or DELETE grants — ever.** See [docs/secrets.md](secrets.md),
[.claude/rules/sql.md](../.claude/rules/sql.md), and `docs/ops/audit.md`.

```sql
CREATE TABLE audit_log (
    id          BIGSERIAL,
    ts          TIMESTAMPTZ NOT NULL,
    actor       TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    entity_type TEXT        NOT NULL,
    entity_id   TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}',
    prev_hash   BYTEA,
    row_hash    BYTEA       NOT NULL
) PARTITION BY RANGE (ts);
```

`ensure_audit_partitions()` auto-creates the next N months. `audit_checkpoints` (migration `0014`)
periodically signs and exports the chain to S3/MinIO for WORM verification; `audit_chain_status`
(`0030`) records the result of each verification run. Writes are live today via
`BaseWorker._finish_completed` on every worker run completion — this is true even though most of
the FastAPI services in `services/` aren't deployed (see `architecture.md §3.1`).

### `prices_daily` (hypertable)

```sql
CREATE TABLE prices_daily (
    instrument_id BIGINT      NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    open, high, low, close     NUMERIC(18,8),
    volume                     NUMERIC(18,8)
);
SELECT create_hypertable('prices_daily', 'ts', chunk_time_interval => INTERVAL '1 month');
```

Compressed after 90 days. `prices_intraday` is the same shape with a 7-day chunk interval and no
compression. Other hypertables follow the same pattern: `macro_indicators` (1-year chunks),
`signals` (1-month, realigned in `0027`), `risk_metrics` (1-month), `paper_fund_snapshots`
(1-week).

## Roles

| Role | Access |
|------|--------|
| `tb_app` | Full DML on operational tables; `audit_log` insert+select only (no update/delete) |
| `tb_rnd_readonly` | Read-only on most tables; narrow inserts into `proposals`, `agent_runs`, `model_runs`, `agent_reports`; no raw `audit_log` access — only the `system_audit_summary` view |
| `litellm` | Separate database owner for the LiteLLM proxy (its own DB, migration `0012`) |

Full role/grant detail: [docs/infra/database-roles.md](infra/database-roles.md).

## Migration Conventions

- Alembic only; see [.claude/rules/sql.md](../.claude/rules/sql.md)
- All FKs `ON DELETE RESTRICT` unless an ADR justifies otherwise
- All timestamps `TIMESTAMPTZ NOT NULL`
- `create_hypertable()` in the same migration as `CREATE TABLE`
- `audit_log` and `audit_checkpoints` are append-only — never add `UPDATE`/`DELETE` grants
- New migrations should extend the domain table in `architecture.md §4.1`, not introduce a new
  Postgres schema — the single-schema design is deliberate, not an accident to fix

## Empty tables are often correct, not broken

`risk_metrics` is empty today because `portfolio_id` is a `NOT NULL` FK and the platform has zero
live portfolios/positions — not because a writer is missing. Don't seed synthetic rows to make a
dashboard look populated; check `SERVICES_STATUS.md` and `docs/ops/risk-metrics-activation.md`
for the real activation checklist first.
