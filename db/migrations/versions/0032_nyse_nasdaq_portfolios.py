"""nyse_nasdaq_portfolios

Revision ID: 0032_nyse_nasdaq_portfolios
Revises: 0031_zinc_fund_tracking

Register NYSE (PA3R4GMBBJYK) and NASDAQ (PA3LJ8OA4X7R) as named paper
sub-accounts with linked portfolios so fund snapshots can be tracked
independently for each sub-account.
"""

from alembic import op

revision = "0032_nyse_nasdaq_portfolios"
down_revision = "0031_zinc_fund_tracking"

SQL_UP = """
INSERT INTO theeyebeta.accounts (id, external_id, broker, mode, metadata)
VALUES
  ('d30e8400-e29b-41d4-a716-446655440005', 'PA3R4GMBBJYK', 'alpaca', 'paper',
   '{"display_name": "NYSE", "sub_account": true}'),
  ('e30e8400-e29b-41d4-a716-446655440007', 'PA3LJ8OA4X7R', 'alpaca', 'paper',
   '{"display_name": "NASDAQ", "sub_account": true}')
ON CONFLICT (external_id) DO NOTHING;

INSERT INTO theeyebeta.portfolios (id, account_id, name, mandate)
VALUES
  ('d40e8400-e29b-41d4-a716-446655440006',
   'd30e8400-e29b-41d4-a716-446655440005',
   'nyse-individual',
   '{"strategy": "nyse_stocks", "description": "NYSE-listed individual stock paper portfolio"}'),
  ('e40e8400-e29b-41d4-a716-446655440008',
   'e30e8400-e29b-41d4-a716-446655440007',
   'nasdaq-individual',
   '{"strategy": "nasdaq_stocks", "description": "NASDAQ-listed individual stock paper portfolio"}')
ON CONFLICT (id) DO NOTHING;
"""

SQL_DOWN = """
DELETE FROM theeyebeta.portfolios
  WHERE id IN ('d40e8400-e29b-41d4-a716-446655440006',
               'e40e8400-e29b-41d4-a716-446655440008');
DELETE FROM theeyebeta.accounts
  WHERE id IN ('d30e8400-e29b-41d4-a716-446655440005',
               'e30e8400-e29b-41d4-a716-446655440007');
"""


def upgrade() -> None:
    """Register NYSE and NASDAQ paper sub-accounts and portfolios."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove NYSE and NASDAQ sub-account seed rows."""
    op.execute(SQL_DOWN)
