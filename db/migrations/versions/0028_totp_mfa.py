"""totp_mfa

Revision ID: 0028_totp_mfa
Revises: 0027_signals_schema_realign

TOTP MFA columns on admin_users.
"""

from alembic import op

revision = "0028_totp_mfa"
down_revision = "0027_signals_schema_realign"

SQL_UP = """
ALTER TABLE theeyebeta.admin_users
  ADD COLUMN IF NOT EXISTS totp_secret TEXT,
  ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS totp_verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS totp_backup_codes TEXT[],
  ADD COLUMN IF NOT EXISTS mfa_failed_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS mfa_locked_until TIMESTAMPTZ;
"""

SQL_DOWN = """
ALTER TABLE theeyebeta.admin_users
  DROP COLUMN IF EXISTS mfa_locked_until,
  DROP COLUMN IF EXISTS mfa_failed_attempts,
  DROP COLUMN IF EXISTS totp_backup_codes,
  DROP COLUMN IF EXISTS totp_verified_at,
  DROP COLUMN IF EXISTS totp_enabled,
  DROP COLUMN IF EXISTS totp_secret;
"""


def upgrade() -> None:
    """Add TOTP MFA columns to admin_users."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Remove TOTP MFA columns from admin_users."""
    op.execute(SQL_DOWN)
