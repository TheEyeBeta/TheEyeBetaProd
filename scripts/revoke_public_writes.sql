-- One-time June 30 deprecation: freeze public.* as read-only for tb_app.
-- Run as postgres on the Mac mini after Prod cutover is verified:
--   psql "$DATABASE_URL" -f scripts/revoke_public_writes.sql

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public FROM tb_app;
REVOKE USAGE, CREATE ON SCHEMA public FROM tb_app;
GRANT USAGE ON SCHEMA public TO tb_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tb_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM tb_app;
