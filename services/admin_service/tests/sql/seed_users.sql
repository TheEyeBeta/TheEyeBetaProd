-- Seed admin RBAC users for integration tests.
-- Password for all users: test-password-123

INSERT INTO theeyebeta.admin_users (
  id, username, password_hash, display_name, email, active, mfa_enabled
) VALUES
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'master-admin',
    '$2b$12$6nLjwVTY1uY24aA6HlY.QOZVA11wjhIA4ZlMT2b0.y8QU0GYyhOCG',
    'Master Admin',
    'master@theeyebeta.local',
    true,
    false
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'operator-one',
    '$2b$12$6nLjwVTY1uY24aA6HlY.QOZVA11wjhIA4ZlMT2b0.y8QU0GYyhOCG',
    'Operator One',
    'operator@theeyebeta.local',
    true,
    true
  )
ON CONFLICT (username) DO NOTHING;

INSERT INTO theeyebeta.admin_user_roles (user_id, role_id, granted_by)
SELECT 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', r.id, 'seed'
  FROM theeyebeta.admin_roles r WHERE r.name = 'operator'
ON CONFLICT DO NOTHING;

INSERT INTO theeyebeta.admin_user_roles (user_id, role_id, granted_by)
SELECT 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', r.id, 'seed'
  FROM theeyebeta.admin_roles r WHERE r.name = 'MASTER_ADMIN'
ON CONFLICT DO NOTHING;

INSERT INTO theeyebeta.admin_user_roles (user_id, role_id, granted_by)
SELECT 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', r.id, 'seed'
  FROM theeyebeta.admin_roles r WHERE r.name = 'operator'
ON CONFLICT DO NOTHING;
