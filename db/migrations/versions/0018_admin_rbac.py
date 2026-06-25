"""admin RBAC — operator users, roles, sessions

Revision ID: 0018_admin_rbac
Revises: 0017_guard_violations_resolution
"""

from alembic import op

revision = "0018_admin_rbac"
down_revision = "0017_guard_violations_resolution"

SQL_UP = """
CREATE TABLE theeyebeta.admin_roles (
  id          smallserial PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  description text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.admin_users (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username          text NOT NULL UNIQUE,
  password_hash     text NOT NULL,
  display_name      text,
  email             text,
  active            boolean NOT NULL DEFAULT true,
  mfa_enabled       boolean NOT NULL DEFAULT false,
  mfa_secret_version smallint NOT NULL DEFAULT 0,
  last_login_at     timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE theeyebeta.admin_user_roles (
  user_id     uuid NOT NULL REFERENCES theeyebeta.admin_users(id) ON DELETE CASCADE,
  role_id     smallint NOT NULL REFERENCES theeyebeta.admin_roles(id) ON DELETE RESTRICT,
  granted_by  text NOT NULL,
  granted_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE theeyebeta.admin_user_sessions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES theeyebeta.admin_users(id) ON DELETE CASCADE,
  refresh_jti  text NOT NULL UNIQUE,
  user_agent   text,
  ip_address   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  revoked_at   timestamptz,
  revoked_by   text
);

CREATE INDEX idx_admin_users_active ON theeyebeta.admin_users(active) WHERE active;
CREATE INDEX idx_admin_user_roles_role ON theeyebeta.admin_user_roles(role_id);
CREATE INDEX idx_admin_user_sessions_user_active
  ON theeyebeta.admin_user_sessions(user_id)
  WHERE revoked_at IS NULL;

INSERT INTO theeyebeta.admin_roles (name, description) VALUES
  ('operator', 'Standard Terminal operator'),
  ('MASTER_ADMIN', 'Full dangerous-action authority');

GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_users TO tb_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON theeyebeta.admin_user_roles TO tb_app;
GRANT SELECT ON theeyebeta.admin_roles TO tb_app;
GRANT SELECT, INSERT, UPDATE ON theeyebeta.admin_user_sessions TO tb_app;
"""

SQL_DOWN = """
DROP TABLE IF EXISTS theeyebeta.admin_user_sessions;
DROP TABLE IF EXISTS theeyebeta.admin_user_roles;
DROP TABLE IF EXISTS theeyebeta.admin_users;
DROP TABLE IF EXISTS theeyebeta.admin_roles;
"""


def upgrade() -> None:
    op.execute(SQL_UP)


def downgrade() -> None:
    op.execute(SQL_DOWN)
