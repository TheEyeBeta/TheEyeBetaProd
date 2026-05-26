"""data_snapshots_packaged
Revision ID: 0011_data_snapshots_packaged
Revises: 0010_data_snapshots
"""

from alembic import op

revision = "0011_data_snapshots_packaged"
down_revision = "0010_data_snapshots"

SQL_UP = """
CREATE TABLE theeyebeta.data_snapshots_packaged (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id     uuid        NOT NULL,
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
CREATE INDEX idx_data_snapshots_packaged_market_date
    ON theeyebeta.data_snapshots_packaged(market, trade_date DESC);
CREATE INDEX idx_data_snapshots_packaged_snapshot_id
    ON theeyebeta.data_snapshots_packaged(snapshot_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.data_snapshots_packaged TO tb_app;
GRANT SELECT ON theeyebeta.data_snapshots_packaged TO tb_rnd_readonly;
"""

SQL_DOWN = "DROP TABLE IF EXISTS theeyebeta.data_snapshots_packaged;"


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
