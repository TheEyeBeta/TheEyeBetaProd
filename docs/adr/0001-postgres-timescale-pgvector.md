# ADR 0001: Postgres + TimescaleDB + pgvector as the Single Relational Substrate

**Status:** Accepted — 2026-05-21  
**Deciders:** Platform team  
**Supersedes:** —  
**Related:** [docs/data-model.md](../data-model.md), [docs/architecture.md §4](../architecture.md#4-data-model)

---

## Context

theeyebeta requires three distinct storage capabilities simultaneously:

1. **Relational / OLTP** — order lifecycle, user state, configuration, audit trail.
   Strong consistency, foreign key integrity, ACID transactions.

2. **Time-series** — market tick data, OHLCV bars, P&L snapshots, VaR history.
   High write throughput (thousands of ticks/second), efficient range scans,
   automatic compression and retention policies.

3. **Vector similarity search** — LLM embeddings for semantic retrieval of past proposals,
   research notes, and relevant historical analogues. Approximate nearest-neighbour
   (ANN) queries with cosine or L2 distance.

The question is: **one database or many?**

### Forces

- We are a small team on a single production host (Mac mini). Operational complexity
  is a first-class cost.
- All three workloads are tightly coupled: a trade order (relational) references ticks
  (time-series) and a research proposal (vector). Cross-workload queries must be possible
  without ETL.
- The `audit_log` table must be append-only and must reference both order IDs and
  tick timestamps in a single atomic write.
- Consistency across workloads matters: we cannot afford a scenario where the OMS sees
  a position that the risk service has not yet seen due to replication lag between
  separate databases.

---

## Decision

We will use a **single PostgreSQL 17 instance** extended with:

- **TimescaleDB** (bundled in `timescale/timescaledb-ha:pg17`) — hypertable-based
  partitioning, continuous aggregates, native compression, and retention policies
  for all time-series data.
- **pgvector** (bundled in the same image) — `vector` column type, HNSW and IVFFlat
  indexes for ANN queries on LLM embeddings.

All three workloads share a single connection pool (asyncpg) and a single schema
namespace (separated by PostgreSQL schemas, not databases).

---

## Consequences

### Positive

- **Single operational surface.** One host, one backup target, one monitoring alert.
  `pg_dump`, `pg_basebackup`, and TimescaleDB continuous backup all work from one
  connection string.
- **Cross-workload joins without ETL.** A single query can join `orders` (relational)
  with `market.ticks` (time-series) and filter by `research.proposals` embedding similarity
  — impossible with separate databases without materialising intermediate results.
- **Atomic writes across concerns.** A trade execution can write to `orders`, `audit_log`,
  and `risk.var_snapshots` in a single transaction with no two-phase commit.
- **Simplified application code.** One `DATABASE_URL`, one connection pool, one Alembic
  target. No per-workload connection management.
- **TimescaleDB continuous aggregates** replace ad-hoc GROUP BY queries for OHLCV
  roll-ups and P&L summaries with materialised, auto-refreshing views.
- **pgvector HNSW indexes** give < 5 ms ANN query latency at the embedding scales we
  target (< 1 M vectors), with no separate infrastructure.

### Negative

- **Single point of failure.** A Postgres outage affects all workloads simultaneously.
  Mitigation: TimescaleDB streaming replication to a hot-standby replica (planned).
- **Write contention.** High-frequency tick writes and OLTP writes share the same WAL
  and autovacuum budget. Mitigation: separate tablespaces; TimescaleDB compression
  reduces live chunk footprint; connection pool tuning.
- **HNSW index build time.** Building or rebuilding an HNSW index on > 500 K vectors
  is CPU-intensive and blocks some maintenance operations. Mitigation: build indexes
  during low-traffic windows with `CREATE INDEX CONCURRENTLY`.
- **No horizontal write scaling.** Postgres is a single-writer system. If tick ingest
  exceeds the host's I/O budget, we will need to shard or offload to a dedicated
  time-series store. That decision would be captured in a future ADR.

### Neutral

- TimescaleDB's chunk interval (1 day for ticks) must be set at table creation time.
  Changing it later requires migrating data — choose carefully.
- pgvector's `vector(1536)` dimension is fixed per column. OpenAI `text-embedding-3-small`
  produces 1 536-dimensional embeddings; Claude does not expose embeddings directly.
  We will use the OpenAI embedding model for now.

---

## Alternatives Considered

| Option | Description | Why rejected |
|--------|-------------|-------------|
| **Postgres + ClickHouse** | Relational + columnar OLAP | Two databases to operate; no vector support; ETL overhead for cross-workload queries |
| **Postgres + QuestDB** | Relational + purpose-built time-series | QuestDB lacks pgvector; adds another operational dependency; SQL dialect divergence |
| **Postgres + Qdrant** | Relational + dedicated vector DB | Three databases (Postgres + Qdrant + some time-series store); cross-workload queries require application-level joins; Qdrant adds ~400 MB RAM overhead on a constrained host |
| **Postgres + TimescaleDB + Qdrant** | Without pgvector | Qdrant adds operational overhead; pgvector at our scale (< 1 M vectors) has comparable performance; avoids a third stateful service |
| **Single Postgres without extensions** | Vanilla Postgres | No automatic time-series partitioning or compression; no ANN index support; would require manual partitioning and full-table kNN scans |
| **CockroachDB** | Distributed SQL | Distributes writes horizontally but is operationally heavier; no TimescaleDB; no pgvector; not appropriate for a single-host deployment |

---

## References

- [docs/architecture.md §4 — Data Model](../architecture.md#4-data-model)
- [docs/data-model.md](../data-model.md)
- [TimescaleDB documentation](https://docs.timescale.com/)
- [pgvector — HNSW indexing](https://github.com/pgvector/pgvector#hnsw)
- [timescale/timescaledb-ha Docker image](https://hub.docker.com/r/timescale/timescaledb-ha)
- [infra/postgres/init/01-extensions.sql](../../infra/postgres/init/01-extensions.sql)
