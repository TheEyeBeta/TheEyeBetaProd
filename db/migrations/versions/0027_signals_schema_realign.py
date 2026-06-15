"""signals_schema_realign

Revision ID: 0027_signals_schema_realign
Revises: 0026_admin_rbac

Realign theeyebeta.signals to match the engine's actual write schema.

Investigation (2026-06-16): The engine (TheEyeBetaLocal/services/engine) writes:
  INSERT INTO signals (ticker_id, ts, strategy_name, signal, confidence,
                       entry_price, target_price, stop_loss, metadata)
using an unqualified table name.  The current theeyebeta.signals (created in 0006)
has an incompatible schema: (strategy_id, instrument_id, ts, side, strength,
features).  No cutover is possible without schema alignment.

Activation checklist (issue #3):
  1. Apply this migration (alembic upgrade 0027_signals_schema_realign).
  2. In TheEyeBetaLocal/services/engine/src/engine/db.py, add
       server_settings={"search_path": "theeyebeta,public"}
     to asyncpg.create_pool().  The schema-init block already forces
     SET search_path TO public, so engine housekeeping tables (tickers,
     price_ticks, etc.) remain in public.
  3. Restart the engine.  Verify rows appear in theeyebeta.signals.
  4. Backfill: INSERT INTO theeyebeta.signals (...) SELECT ... FROM public.signals
     ON CONFLICT DO NOTHING, in batches by signal_id.
  5. After zero new writes to public.signals for 48 h, drop public.signals.
"""

from alembic import op

revision = "0027_signals_schema_realign"
down_revision = "0026_admin_rbac"

SQL_UP = """
-- Preserve incompatible early-test data (2026-01-16..2026-02-09).
ALTER TABLE theeyebeta.signals RENAME TO signals_v1_archive;

-- New theeyebeta.signals matches engine write schema exactly.
CREATE TABLE theeyebeta.signals (
    signal_id       BIGSERIAL,
    ticker_id       BIGINT NOT NULL REFERENCES public.tickers(ticker_id)
                        ON UPDATE CASCADE ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL,
    strategy_name   VARCHAR(64) NOT NULL,
    signal          VARCHAR(16) NOT NULL
                        CHECK (signal IN ('BUY', 'SELL', 'HOLD', 'STRONG_BUY', 'STRONG_SELL')),
    confidence      NUMERIC(5, 4),
    entry_price     NUMERIC(18, 6),
    target_price    NUMERIC(18, 6),
    stop_loss       NUMERIC(18, 6),
    metadata        JSONB,
    UNIQUE (ticker_id, ts, strategy_name)
);
SELECT create_hypertable(
    'theeyebeta.signals', 'ts',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists => TRUE
);
CREATE INDEX ON theeyebeta.signals (ticker_id, ts DESC);

GRANT SELECT, INSERT, UPDATE ON theeyebeta.signals TO tb_app;
GRANT SELECT ON theeyebeta.signals TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.signals;
ALTER TABLE theeyebeta.signals_v1_archive RENAME TO signals;
"""


def upgrade() -> None:
    """Replace theeyebeta.signals with engine-compatible schema; archive old table."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Restore original theeyebeta.signals from archive."""
    op.execute(SQL_DOWN)
