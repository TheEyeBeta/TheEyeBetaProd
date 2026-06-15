"""signals_status_comment

Revision ID: 0025_signals_status_comment
Revises: 0024_public_ticker_map

Document the status of theeyebeta.signals directly on the table.

Investigation (2026-06-15): theeyebeta.signals is stale (rows only 2026-01-16..02-09)
but is NOT deprecated. Per scripts/diagnose_db_state.py it is the *forward* target for
the signals stream — public.signals (being deprecated) is where the live producer still
writes. The cutover (point the producer's search_path at theeyebeta,public, then backfill
public.signals -> theeyebeta.signals) is pending and lives in the engine tree, so no
writer is added here. This migration records that status on the table so the staleness
is not mistaken for an outage.
"""

from alembic import op

revision = "0025_signals_status_comment"
down_revision = "0024_public_ticker_map"

SQL_UP = """
COMMENT ON TABLE theeyebeta.signals IS
  'Forward target for the signals stream (hypertable). NOT deprecated. As of 2026-06 the '
  'live producer still writes public.signals (being deprecated); existing rows '
  '(2026-01-16..2026-02-09) are early-test data. Writer cutover pending: set the producer '
  'search_path to theeyebeta,public so new signals land here, then backfill from '
  'public.signals. Ref: scripts/diagnose_db_state.py.';
"""

SQL_DOWN = """
COMMENT ON TABLE theeyebeta.signals IS NULL;
"""


def upgrade() -> None:
    """Record forward-target / cutover-pending status on theeyebeta.signals."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove the status comment."""
    op.execute(SQL_DOWN)
