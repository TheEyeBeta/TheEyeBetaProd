-- theeyebeta revision 0013_prices_intraday
-- 15-minute delayed intraday bars (replaces legacy bar_seconds layout if absent).

BEGIN;

-- If legacy table from 0002_prices exists with bar_seconds, rename aside once.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'theeyebeta'
           AND table_name = 'prices_intraday'
           AND column_name = 'bar_seconds'
    ) THEN
        ALTER TABLE theeyebeta.prices_intraday RENAME TO prices_intraday_legacy_0002;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS theeyebeta.prices_intraday (
    instrument_id bigint NOT NULL REFERENCES theeyebeta.instruments(id),
    ts            timestamptz NOT NULL,
    open          numeric(16, 6),
    high          numeric(16, 6),
    low           numeric(16, 6),
    close         numeric(16, 6),
    volume        bigint,
    source        text NOT NULL,
    ingested_at   timestamptz NOT NULL DEFAULT now()
);

SELECT create_hypertable(
    'theeyebeta.prices_intraday',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_intraday_inst_ts
    ON theeyebeta.prices_intraday (instrument_id, ts);

ALTER TABLE theeyebeta.prices_intraday
    SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument_id');
SELECT add_compression_policy('theeyebeta.prices_intraday', INTERVAL '7 days', if_not_exists => TRUE);

INSERT INTO theeyebeta.alembic_version (version_num)
VALUES ('0013_prices_intraday')
ON CONFLICT (version_num) DO NOTHING;

COMMIT;

-- downgrade:
-- BEGIN;
-- SELECT remove_compression_policy('theeyebeta.prices_intraday', if_exists => TRUE);
-- DROP TABLE IF EXISTS theeyebeta.prices_intraday;
-- ALTER TABLE IF EXISTS theeyebeta.prices_intraday_legacy_0002 RENAME TO prices_intraday;
-- DELETE FROM theeyebeta.alembic_version WHERE version_num = '0013_prices_intraday';
-- COMMIT;
