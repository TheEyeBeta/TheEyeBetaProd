# Data Model

> **Status:** Stub — expand as migrations are written.
> See [architecture.md §4](architecture.md#4-data-model) for the schema map.

## PostgreSQL Extensions

All enabled in `infra/postgres/init/01-extensions.sql`:

- `timescaledb` — time-series partitioning, continuous aggregates, compression
- `vector` (pgvector) — ANN similarity search on embeddings
- `uuid-ossp` — `gen_random_uuid()` for primary keys
- `pg_stat_statements` — query performance monitoring

## Schema Overview

_Schemas are created in migration module 0001-bootstrap._

| Schema | Purpose |
|--------|---------|
| `public` | Cross-cutting: users, instruments, audit_log |
| `market` | Time-series: ticks, ohlcv (TimescaleDB hypertables) |
| `orders` | Order lifecycle, fills, positions |
| `risk` | Limits, VaR snapshots |
| `research` | Agent proposals, backtest runs and results |
| `compliance` | Rule checks, alerts, audit references |

## Key Tables

_Full ERD: TODO (generate with `tberd` after migrations run)._

### `audit_log` (public schema)

Append-only. **No UPDATE or DELETE grants on this table — ever.**
See [docs/secrets.md](secrets.md) and [.claude/rules/sql.md](../.claude/rules/sql.md).

```sql
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT        NOT NULL,
    actor_id    UUID,
    entity_type TEXT        NOT NULL,
    entity_id   TEXT        NOT NULL,
    payload     JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `ticks` (market schema)

TimescaleDB hypertable, chunk interval 1 day.

```sql
CREATE TABLE market.ticks (
    ts        TIMESTAMPTZ NOT NULL,
    symbol    TEXT        NOT NULL,
    bid       NUMERIC(18,8) NOT NULL,
    ask       NUMERIC(18,8) NOT NULL,
    last      NUMERIC(18,8),
    volume    NUMERIC(18,8)
);
SELECT create_hypertable('market.ticks', 'ts', chunk_time_interval => INTERVAL '1 day');
```

## Migration Conventions

- Alembic only; see [.claude/rules/sql.md](../.claude/rules/sql.md)
- One migration per module (see architecture.md §4.2)
- All FKs `ON DELETE RESTRICT`
- All timestamps `TIMESTAMPTZ NOT NULL`
- `create_hypertable()` in the same migration as `CREATE TABLE`
