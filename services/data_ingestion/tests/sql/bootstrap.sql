-- Test DB bootstrap (run as superuser before Alembic migrations).
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS theeyebeta;

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tb_app') THEN
    CREATE ROLE tb_app WITH LOGIN PASSWORD 'tb_app_test';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tb_rnd_readonly') THEN
    CREATE ROLE tb_rnd_readonly WITH LOGIN PASSWORD 'tb_rnd_readonly_test';
  END IF;
END
$$;

GRANT CONNECT ON DATABASE theeyebeta TO tb_app;
GRANT ALL ON SCHEMA theeyebeta TO tb_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA theeyebeta GRANT ALL ON TABLES TO tb_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA theeyebeta GRANT ALL ON SEQUENCES TO tb_app;
