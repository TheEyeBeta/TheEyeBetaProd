"""Admin user TOTP secret storage for real MFA enforcement

Revision ID: 0028_admin_user_totp
Revises: 0027_admin_command_control
"""

from alembic import op

revision = "0028_admin_user_totp"
down_revision = "0027_admin_command_control"

SQL_UP = """
ALTER TABLE theeyebeta.admin_users
  ADD COLUMN totp_secret text;
"""

SQL_DOWN = """
ALTER TABLE theeyebeta.admin_users
  DROP COLUMN IF EXISTS totp_secret;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
