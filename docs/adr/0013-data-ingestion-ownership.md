# ADR 0013 — theeyebeta owns its own data ingestion

Date: 2026-05-22
Status: Accepted (supersedes [ADR 0012](0012-public-schema-bridge.md))

> Renumbered from its original `0002` on 2026-06-18 — that number collided with the unrelated
> `0002-nats-jetstream-over-kafka.md` from a later ADR batch. See `docs/build-log.md` (entry
> "P-ADR-04 — ADR-0002-b") if cross-checking against historical notes.

## Context

The legacy data provider feeding `public.*` is being deprecated. Bridging to
`public` would inherit a dying upstream. `theeyebeta` must own its inputs end to
end so its data quality and freshness are independent of the legacy system.

`public.*` becomes a read-only historical archive. The new system does not
read it at runtime. If historical backfill is ever needed (e.g., to bootstrap
a 5-year backtest before fresh ingestion has accumulated enough history),
that is a one-off ETL job, not a runtime dependency.

## Decision

- `theeyebeta` owns ingestion. A `data_ingestion` microservice pulls stock
  prices, macro indicators (Phase 3), and news (Phase 4) into `theeyebeta.*`
  tables.
- Adapter pattern: one Python class per upstream source. `yfinance` and FRED
  ship first; `alpaca-py` (intraday), news RSS, fundamentals provider added
  incrementally without changing the writer/pipeline.
- Universe lives in `theeyebeta.instruments`, seeded from a YAML manifest the
  operator owns. New tickers are added by editing the YAML and re-seeding.
- Writers use psycopg COPY for bulk inserts; idempotent on `(instrument_id, ts)`
  via `ON CONFLICT DO NOTHING`.

## Consequences

+ Zero runtime coupling to `public.*`. The legacy data provider can be turned
  off without affecting the new system.
+ All input data quality is `theeyebeta`'s responsibility — we control the
  schema, the validation, the lineage.
- Historical data must be rebuilt from each upstream's available history
  (yfinance: ~30 years for US, varies elsewhere; FRED: long histories).
- Backfill takes time on first run; budget a few hours of API calls.
