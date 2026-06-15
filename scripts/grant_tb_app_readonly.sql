-- Read-only grants for tb_app CLI queries against canonical theeyebeta tables.
-- Safe to re-run.

GRANT USAGE ON SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.ind_technical_daily TO tb_app;
GRANT SELECT ON theeyebeta.public_ticker_map TO tb_app;
GRANT SELECT ON theeyebeta.macro_regime_snapshots TO tb_app;
GRANT SELECT ON theeyebeta.sector_daily TO tb_app;
