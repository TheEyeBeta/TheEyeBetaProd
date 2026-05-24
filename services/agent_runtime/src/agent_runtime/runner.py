"""Agent run lifecycle: snapshot → LLM → guard → persist."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
import structlog

from .constitution import load_constitution
from .guard import GuardViolation, validate_output
from .llm_client import LLMClient

log = structlog.get_logger()


def _db_url() -> str:
    return os.environ["DATABASE_URL"].replace("+psycopg", "").replace("+asyncpg", "")


def _resolve_constitution(path_str: str) -> Path:
    """Resolve constitution path relative to repo root when not absolute."""
    p = Path(path_str)
    if p.is_file():
        return p
    repo_root = Path(__file__).resolve().parents[4]
    candidate = repo_root / path_str
    if candidate.is_file():
        return candidate
    return p


async def run_agent(agent_id: str, market: str, trade_date: date) -> dict:
    """Execute one agent run against a market snapshot.

    Args:
        agent_id: Agent PK in theeyebeta.agents (e.g. ``technical-analyst``).
        market: MIC exchange code (e.g. ``XNAS``).
        trade_date: Trading date of the snapshot to analyse.

    Returns:
        Summary dict with run_id, decision ids, cost, tokens, stance, regime.

    Raises:
        ValueError: Agent inactive or snapshot missing.
        GuardViolation: Output failed guard checks (run marked failed in DB).
    """
    run_id = uuid4()

    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        cur = await conn.execute(
            """
            SELECT constitution_path, model_default
              FROM theeyebeta.agents
             WHERE id = %s AND active
            """,
            (agent_id,),
        )
        row = await cur.fetchone()
        if not row:
            raise ValueError(f"Agent {agent_id} not found or inactive")
        const_path, _model_default = row

        cur2 = await conn.execute(
            """
            SELECT id, blob_uri, universe_size
              FROM theeyebeta.data_snapshots
             WHERE market = %s AND trade_date = %s
             ORDER BY schema_version DESC
             LIMIT 1
            """,
            (market, trade_date),
        )
        snap_row = await cur2.fetchone()
        if not snap_row:
            raise ValueError(f"No snapshot for {market} on {trade_date}")
        snap_id, blob_uri, _ = snap_row

        await conn.execute(
            """
            INSERT INTO theeyebeta.agent_runs
                (id, agent_id, triggered_by, snapshot_id, status)
            VALUES (%s, %s, %s, %s, 'running')
            """,
            (run_id, agent_id, f"cli:{agent_id}", snap_id),
        )
        await conn.commit()

    try:
        constitution = load_constitution(_resolve_constitution(const_path))
        blob_path = Path(blob_uri.removeprefix("file://"))
        snapshot_data = json.loads(blob_path.read_text())
        valid_symbols = {u["symbol"] for u in snapshot_data["universe"]}

        user_msg = (
            f"Snapshot below for market={market} trade_date={trade_date}. "
            f"Produce decisions per your output schema.\n\n"
            f"```json\n{json.dumps(snapshot_data, indent=2)}\n```"
        )

        client = LLMClient()
        result = await client.chat(
            model=constitution.model,
            system=constitution.system_prompt,
            user=user_msg,
            max_tokens=2000,
            temperature=0.0,
        )

        parsed = validate_output(result.text, valid_symbols)

        async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
            await conn.execute(
                """
                INSERT INTO theeyebeta.model_runs
                    (run_id, provider, model, input_tokens, output_tokens,
                     cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, status)
                VALUES (%s, 'openai', %s, %s, %s, %s, %s, %s, %s, 'ok')
                """,
                (
                    run_id,
                    result.model,
                    result.input_tokens,
                    result.output_tokens,
                    result.cache_read_tokens,
                    result.cache_write_tokens,
                    result.cost_usd,
                    result.latency_ms,
                ),
            )

            sym_to_id = {u["symbol"]: u["instrument_id"] for u in snapshot_data["universe"]}
            decision_ids: list[str] = []
            for d in parsed.decisions:
                iid = sym_to_id.get(d.instrument_symbol)
                evidence = {
                    "key_drivers": d.key_drivers,
                    "snapshot_id": str(snap_id),
                    "blob_sha256_prefix": None,
                    "market_stance": parsed.market_stance,
                    "regime_call": parsed.regime_call,
                }
                cur3 = await conn.execute(
                    """
                    INSERT INTO theeyebeta.agent_decisions
                        (run_id, instrument_id, market, decision, confidence,
                         rationale, evidence, horizon_days)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING id
                    """,
                    (
                        run_id,
                        iid,
                        market,
                        d.decision,
                        d.confidence,
                        d.rationale,
                        json.dumps(evidence),
                        d.horizon_days,
                    ),
                )
                dec_row = await cur3.fetchone()
                decision_ids.append(str(dec_row[0]))

            await conn.execute(
                """
                UPDATE theeyebeta.agent_runs
                   SET status = 'succeeded',
                       ended_at = now(),
                       total_input_tokens = %s,
                       total_output_tokens = %s,
                       total_cost_usd = %s
                 WHERE id = %s
                """,
                (
                    result.input_tokens,
                    result.output_tokens,
                    result.cost_usd,
                    run_id,
                ),
            )
            await conn.commit()

        log.info(
            "agent_run_succeeded",
            run_id=str(run_id),
            market=market,
            decisions=len(decision_ids),
            cost_usd=result.cost_usd,
        )

        return {
            "run_id": str(run_id),
            "decisions": decision_ids,
            "cost_usd": result.cost_usd,
            "latency_ms": result.latency_ms,
            "tokens": {"input": result.input_tokens, "output": result.output_tokens},
            "market_stance": parsed.market_stance,
            "regime_call": parsed.regime_call,
        }

    except GuardViolation as gv:
        async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
            await conn.execute(
                """
                INSERT INTO theeyebeta.guard_violations
                    (run_id, agent_id, violation_type, severity, detail, resolution)
                VALUES (%s, %s, %s, 'high', %s::jsonb, 'reject')
                """,
                (
                    run_id,
                    agent_id,
                    gv.db_violation_type,
                    json.dumps({"kind": gv.kind, "detail": gv.detail}),
                ),
            )
            await conn.execute(
                """
                UPDATE theeyebeta.agent_runs
                   SET status = 'failed', ended_at = now(), error = %s
                 WHERE id = %s
                """,
                (str(gv)[:500], run_id),
            )
            await conn.commit()
        raise

    except Exception as exc:
        async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
            await conn.execute(
                """
                UPDATE theeyebeta.agent_runs
                   SET status = 'failed', ended_at = now(), error = %s
                 WHERE id = %s
                """,
                (str(exc)[:500], run_id),
            )
            await conn.commit()
        raise
