"""Postgres persistence for backtest runs."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import psycopg
import structlog

log = structlog.get_logger()


async def insert_backtest_run(
    dsn: str,
    *,
    strategy_id: str,
    start_date: date,
    end_date: date,
    universe: str,
    config: dict[str, Any],
    git_sha: str,
) -> UUID:
    """Insert a running backtest row."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            INSERT INTO theeyebeta.backtest_runs
                (strategy_id, start_date, end_date, universe, config, git_sha, status)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, 'running')
            RETURNING id
            """,
            (
                strategy_id,
                start_date,
                end_date,
                universe,
                json.dumps(config),
                git_sha,
            ),
        )
        row = await cur.fetchone()
        await conn.commit()
    run_id = row[0]
    log.info("backtest_run_inserted", backtest_id=str(run_id), strategy_id=strategy_id)
    return run_id


async def update_run_universe(
    dsn: str,
    run_id: UUID,
    *,
    universe: str,
    config: dict[str, Any],
) -> None:
    """Patch universe and config after resolution."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            UPDATE theeyebeta.backtest_runs
               SET universe = %s,
                   config = %s::jsonb
             WHERE id = %s
            """,
            (universe, json.dumps(config), run_id),
        )
        await conn.commit()


async def update_run_status(
    dsn: str,
    run_id: UUID,
    *,
    status: str,
    result_blob_uri: str | None = None,
) -> None:
    """Update run status and optional result URI."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute(
            """
            UPDATE theeyebeta.backtest_runs
               SET status = %s,
                   ended_at = %s,
                   result_blob_uri = COALESCE(%s, result_blob_uri)
             WHERE id = %s
            """,
            (status, datetime.now(tz=UTC), result_blob_uri, run_id),
        )
        await conn.commit()


async def insert_metrics(dsn: str, run_id: UUID, metrics: list[tuple[str, float]]) -> None:
    """Persist metric rows."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        for metric, value in metrics:
            await conn.execute(
                """
                INSERT INTO theeyebeta.backtest_results (backtest_id, metric, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (backtest_id, metric) DO UPDATE SET value = EXCLUDED.value
                """,
                (run_id, metric, value),
            )
        await conn.commit()


async def fetch_run_status(dsn: str, run_id: UUID) -> dict[str, Any] | None:
    """Load status fields for one run."""
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT id, strategy_id, status, started_at, ended_at, result_blob_uri
              FROM theeyebeta.backtest_runs
             WHERE id = %s
            """,
            (run_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "strategy_id": row[1],
        "status": row[2],
        "started_at": row[3].isoformat() if row[3] else None,
        "ended_at": row[4].isoformat() if row[4] else None,
        "result_blob_uri": row[5],
    }


async def fetch_run_results(dsn: str, run_id: UUID) -> dict[str, Any] | None:
    """Load metrics and blob URI for one run."""
    status = await fetch_run_status(dsn, run_id)
    if status is None:
        return None
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        cur = await conn.execute(
            """
            SELECT metric, value
              FROM theeyebeta.backtest_results
             WHERE backtest_id = %s
             ORDER BY metric
            """,
            (run_id,),
        )
        rows = await cur.fetchall()
    metrics = {str(r[0]): float(r[1]) for r in rows}
    return {
        **status,
        "metrics": metrics,
        "result_blob_uri": status.get("result_blob_uri"),
    }
