# ADR 0001 — Use public.* as Data Bridge for theeyebeta

Date: 2026-03-01
Status: Superseded by ADR 0002 — 2026-05-22

## Context

A legacy market-data platform (internal codename: System B) had been running in
the `public` schema of the shared PostgreSQL instance for several years, ingesting
equities prices, corporate actions, exchange metadata, and signals. Rather than
building a dedicated ingestion pipeline from scratch, the initial plan was for
`theeyebeta` to read directly from that `public.*` data via cross-schema queries
(the "bridge" approach). This would accelerate time-to-first-signal by reusing
existing data without duplication.

## Decision

`theeyebeta` reads reference and time-series data from `public.*` at runtime.
Schema-qualified queries (`SELECT * FROM public.signals …`) provide access to
the legacy data without copying it. The `search_path` for all application roles
is set to `theeyebeta, public` so that unqualified table references fall through
to the public schema as a fallback.

## Consequences

- Rapid bootstrapping with existing historical data (System B's data goes back
  several years for many instruments).
- Runtime coupling: `theeyebeta` availability becomes partially dependent on
  System B's schema stability and ingestion health.
- Any schema change in `public.*` (column type change, table rename) can break
  `theeyebeta` queries silently.
- Shared instance resource contention: System B's heavy TimescaleDB workload
  (96 GB, continuous aggregates) competes with `theeyebeta` queries.
- Difficult to guarantee data quality, freshness, or lineage for data owned by
  System B.
