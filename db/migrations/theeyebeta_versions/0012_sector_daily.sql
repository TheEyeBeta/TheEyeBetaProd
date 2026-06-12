-- theeyebeta revision 0012_sector_daily
-- Reversible sector aggregate table for canonical Argos context.

BEGIN;

CREATE TABLE IF NOT EXISTS theeyebeta.sector_daily (
    sector               text NOT NULL,
    as_of_date           date NOT NULL,
    n_instruments        integer NOT NULL DEFAULT 0,
    avg_return_1d        numeric(12, 6),
    avg_return_5d        numeric(12, 6),
    avg_return_30d       numeric(12, 6),
    median_rsi_14        numeric(8, 4),
    pct_above_sma_50     numeric(6, 4),
    pct_above_sma_200    numeric(6, 4),
    rel_strength_spx_30d numeric(12, 6),
    rotation_rank        smallint,
    volume_ratio_20d     numeric(12, 6),
    top_contributors     jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sector, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_sector_daily_date
    ON theeyebeta.sector_daily (as_of_date DESC);

-- stamp (schema-qualified version table)
INSERT INTO theeyebeta.alembic_version (version_num)
VALUES ('0012_sector_daily')
ON CONFLICT (version_num) DO NOTHING;

COMMIT;

-- downgrade (run manually):
-- BEGIN;
-- DROP TABLE IF EXISTS theeyebeta.sector_daily;
-- DELETE FROM theeyebeta.alembic_version WHERE version_num = '0012_sector_daily';
-- COMMIT;
