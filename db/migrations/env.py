import asyncio, os
from logging.config import fileConfig
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = None  # we use raw SQL via op.execute; no SQLAlchemy models needed


def do_run_migrations(connection: Connection) -> None:
    connection.execute(text("SET search_path TO theeyebeta, public"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema="theeyebeta",
        include_schemas=True,
        # TimescaleDB create_hypertable cannot run inside a transaction block.
        # AUTOCOMMIT mode is set on the engine; each migration statement
        # auto-commits, so we must NOT wrap in an extra begin_transaction().
        transaction_per_migration=False,
    )
    context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # AUTOCOMMIT: required so TimescaleDB DDL (create_hypertable,
        # add_compression_policy) can commit without an open transaction.
        execution_options={"isolation_level": "AUTOCOMMIT"},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise RuntimeError("Offline mode not supported; use online migrations.")
else:
    run_migrations_online()
