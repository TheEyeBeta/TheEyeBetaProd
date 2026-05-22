-- Run once on first `docker compose up` (scripts in /docker-entrypoint-initdb.d/).
-- Creates the extensions needed by theeyebeta in the default database.

-- pgvector: vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- TimescaleDB is preloaded via shared_preload_libraries in the timescaledb-ha image;
-- explicitly create it here so pg_extension shows it as installed in this DB.
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Useful extras bundled in timescaledb-ha
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
