"""admin_rbac

Revision ID: 0026_admin_rbac
Revises: 0025_signals_status_comment

Minimal RBAC tables for admin-service JWT role enforcement.
"""

from alembic import op

revision = "0026_admin_rbac"
down_revision = "0025_signals_status_comment"

SQL_UP = """
CREATE TABLE theeyebeta.admin_roles (
  id serial PRIMARY KEY,
  name varchar(32) NOT NULL UNIQUE
);

CREATE TABLE theeyebeta.admin_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username varchar(128) NOT NULL UNIQUE,
  email varchar(256),
  password_bcrypt text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.admin_user_roles (
  user_id uuid NOT NULL REFERENCES theeyebeta.admin_users(id) ON DELETE CASCADE,
  role_id integer NOT NULL REFERENCES theeyebeta.admin_roles(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

INSERT INTO theeyebeta.admin_roles (name) VALUES
  ('READ_ONLY'),
  ('COMPLIANCE'),
  ('ANALYST'),
  ('OPERATOR'),
  ('MASTER_ADMIN')
ON CONFLICT (name) DO NOTHING;

CREATE TABLE theeyebeta.prelive_check_cache (
  id bigserial PRIMARY KEY,
  run_at timestamptz NOT NULL,
  overall varchar(16) NOT NULL,
  checks jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_prelive_check_cache_run_at
  ON theeyebeta.prelive_check_cache (run_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE
  ON theeyebeta.admin_users, theeyebeta.admin_roles, theeyebeta.admin_user_roles,
     theeyebeta.prelive_check_cache TO tb_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA theeyebeta TO tb_app;
GRANT SELECT ON theeyebeta.admin_users, theeyebeta.admin_roles,
      theeyebeta.admin_user_roles, theeyebeta.prelive_check_cache TO tb_rnd_readonly;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.prelive_check_cache;
DROP TABLE IF EXISTS theeyebeta.admin_user_roles;
DROP TABLE IF EXISTS theeyebeta.admin_users;
DROP TABLE IF EXISTS theeyebeta.admin_roles;
"""


def upgrade() -> None:
    """Create admin RBAC tables and prelive result cache."""
    op.execute(SQL_UP)


def downgrade() -> None:
    """Drop admin RBAC tables."""
    op.execute(SQL_DOWN)
