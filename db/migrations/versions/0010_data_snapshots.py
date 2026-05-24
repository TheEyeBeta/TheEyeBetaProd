"""data_snapshots
Revision ID: 0010_data_snapshots
Revises: 0009_audit
"""

from alembic import op

revision = "0010_data_snapshots"
down_revision = "0009_audit"

SQL_UP = """
CREATE TABLE theeyebeta.data_snapshots (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    market          text        NOT NULL,
    trade_date      date        NOT NULL,
    schema_version  int         NOT NULL,
    blob_uri        text        NOT NULL,
    blob_sha256     bytea       NOT NULL,
    universe_size   int         NOT NULL,
    packaged_at     timestamptz NOT NULL DEFAULT now(),
    packager_git_sha text,
    UNIQUE (market, trade_date, schema_version)
);
CREATE INDEX idx_data_snapshots_market_date
    ON theeyebeta.data_snapshots(market, trade_date DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.data_snapshots TO tb_app;
GRANT SELECT ON theeyebeta.data_snapshots TO tb_rnd_readonly;
"""

SQL_DOWN = "DROP TABLE IF EXISTS theeyebeta.data_snapshots;"


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
