"""Agent run lifecycle: snapshot → LLM (+ tools) → guard → persist → NATS."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import nats
import psycopg
import structlog
from pydantic import ValidationError

from zinc_schemas.llm_client import LLMClient

from .constitution import AgentConstitution, load_constitution
from .guard import GuardViolation
from .guard_client import GuardRejectedError, validate_agent_output
from .math_tool import MathTool, openai_tool_definition
from .observability import record_run_failure, record_run_success
from .schemas import AgentDecision, AgentOutput, ParsedRunOutput
from .snapshot_context import snapshot_for_llm
from .snapshot_loader import SnapshotLoader

log = structlog.get_logger()


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL", "")
    if not raw:
        msg = "DATABASE_URL must be set"
        raise OSError(msg)
    return raw.replace("+asyncpg", "").replace("+psycopg", "")


def _llm_virtual_key() -> str:
    key = os.environ.get(
        "LITELLM_KEY_AGENT_RUNTIME_EXECUTORS",
        os.environ.get("LITELLM_VIRTUAL_KEY", ""),
    )
    if not key.startswith("sk-"):
        msg = "LITELLM_KEY_AGENT_RUNTIME_EXECUTORS (or LITELLM_VIRTUAL_KEY) must start with sk-"
        raise OSError(msg)
    return key


def _llm_base_url() -> str:
    return os.environ.get("LITELLM_PROXY_URL", "http://llm-gateway:4000").rstrip("/")


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


@dataclass
class _TokenTotals:
    """Accumulated LLM usage for one agent run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class AgentRunner:
    """Execute agents against packaged snapshots."""

    database_url: str = field(default_factory=_db_url)
    llm_base_url: str = field(default_factory=_llm_base_url)
    llm_virtual_key: str = field(default_factory=_llm_virtual_key)

    async def run(
        self,
        agent_id: str,
        snapshot_id: UUID,
        *,
        kind: str = "run",
        agent_messages: list[dict[str, Any]] | None = None,
        parent_run_id: UUID | None = None,
        operator_context: dict[str, Any] | None = None,
        subordinate_reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run one agent against a packaged snapshot.

        Args:
            agent_id: Agent PK in ``theeyebeta.agents``.
            snapshot_id: Packaged snapshot UUID.
            kind: ``run`` (default), ``rebuttal``, or ``rollup`` (department synthesis).
            agent_messages: Peer rationales when ``kind`` is ``rebuttal``.
            parent_run_id: Optional parent run for chain-of-command tracking.
            operator_context: Operator constraints forwarded to the constitution.
            subordinate_reports: Child agent briefings when ``kind`` is ``rollup``.

        Returns:
            Summary with run_id, decision ids, cost, tokens, stance, regime.

        Raises:
            ValueError: Agent inactive or snapshot missing.
            GuardViolation: Output failed guard after retry, fallback, and OBSERVE escalation.
        """
        run_id = uuid4()
        loader = SnapshotLoader(database_url=self.database_url)
        try:
            return await self._run_inner(
                agent_id,
                snapshot_id,
                run_id,
                loader,
                kind=kind,
                agent_messages=agent_messages or [],
                parent_run_id=parent_run_id,
                operator_context=operator_context or {},
                subordinate_reports=subordinate_reports or [],
            )
        finally:
            await loader.aclose()

    async def _run_inner(
        self,
        agent_id: str,
        snapshot_id: UUID,
        run_id: UUID,
        loader: SnapshotLoader,
        *,
        kind: str = "run",
        agent_messages: list[dict[str, Any]] | None = None,
        parent_run_id: UUID | None = None,
        operator_context: dict[str, Any] | None = None,
        subordinate_reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            cur = await conn.execute(
                """
                SELECT constitution_path, model_default, model_fallback
                  FROM theeyebeta.agents
                 WHERE id = %s AND active
                """,
                (agent_id,),
            )
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"Agent {agent_id} not found or inactive")
            const_path, model_default, model_fallback = row

            await conn.execute(
                """
                INSERT INTO theeyebeta.agent_runs
                    (id, agent_id, triggered_by, parent_run_id, snapshot_id, status)
                VALUES (%s, %s, %s, %s, %s, 'running')
                """,
                (run_id, agent_id, f"api:{agent_id}", parent_run_id, snapshot_id),
            )
            await conn.commit()

        try:
            constitution = load_constitution(_resolve_constitution(const_path))
            constitution_model = constitution.model or model_default
            fallback_model = constitution.fallback or model_fallback

            snapshot_data = await loader.load(snapshot_id)

            market = str(snapshot_data.get("market", ""))
            valid_symbols = {u["symbol"] for u in snapshot_data["universe"]}

            async with LLMClient(
                self.llm_virtual_key,
                self.llm_base_url,
                database_url=self.database_url,
                run_id=run_id,
            ) as llm:
                math_tool = MathTool(llm_client=llm)
                parsed_run, totals, raw_text, tool_calls = await self._llm_loop(
                    llm=llm,
                    constitution=constitution,
                    snapshot_id=snapshot_id,
                    snapshot_data=snapshot_data,
                    math_tool=math_tool,
                    model=constitution_model,
                    kind=kind,
                    agent_messages=agent_messages or [],
                    operator_context=operator_context or {},
                    subordinate_reports=subordinate_reports or [],
                )

                if parsed_run.mode == "briefing":
                    assert parsed_run.briefing is not None
                    await self._persist_briefing_success(
                        run_id=run_id,
                        totals=totals,
                    )
                    stance, regime = _briefing_summary_fields(parsed_run.briefing)
                    duration = time.perf_counter() - started
                    record_run_success(
                        agent_id,
                        duration_seconds=duration,
                        input_tokens=totals.input_tokens,
                        output_tokens=totals.output_tokens,
                    )
                    log.info(
                        "agent_briefing_succeeded",
                        run_id=str(run_id),
                        agent_id=agent_id,
                        cost_usd=totals.cost_usd,
                    )
                    return {
                        "run_id": str(run_id),
                        "snapshot_id": str(snapshot_id),
                        "decisions": [],
                        "decision_rows": [],
                        "cost_usd": totals.cost_usd,
                        "market_stance": stance,
                        "regime_call": regime,
                        "briefing": parsed_run.briefing,
                        "kind": kind,
                    }

                assert parsed_run.trading is not None
                parsed = await self._guard_until_pass(
                    agent_id=agent_id,
                    run_id=str(run_id),
                    constitution=constitution,
                    llm=llm,
                    math_tool=math_tool,
                    snapshot_id=snapshot_id,
                    snapshot_data=snapshot_data,
                    parsed=parsed_run.trading,
                    raw_text=raw_text,
                    tool_calls=tool_calls,
                    valid_symbols=valid_symbols,
                    primary_model=constitution_model,
                    fallback_model=fallback_model,
                    totals=totals,
                )

            decision_ids = await self._persist_success(
                run_id=run_id,
                agent_id=agent_id,
                snapshot_id=snapshot_id,
                market=market,
                snapshot_data=snapshot_data,
                parsed=parsed,
                totals=totals,
            )
            sym_to_id = {u["symbol"]: u["instrument_id"] for u in snapshot_data["universe"]}
            decision_rows = []
            for decision_id, decision in zip(decision_ids, parsed.decisions, strict=True):
                decision_rows.append(
                    {
                        "decision_id": decision_id,
                        "instrument_symbol": decision.instrument_symbol,
                        "instrument_id": sym_to_id.get(decision.instrument_symbol),
                        "decision": decision.decision,
                        "confidence": decision.confidence,
                        "horizon_days": decision.horizon_days,
                        "rationale": decision.rationale,
                        "key_drivers": decision.key_drivers,
                    },
                )
            await self._publish_decision_event(agent_id, run_id, parsed, decision_ids)

            duration = time.perf_counter() - started
            record_run_success(
                agent_id,
                duration_seconds=duration,
                input_tokens=totals.input_tokens,
                output_tokens=totals.output_tokens,
            )
            log.info(
                "agent_run_succeeded",
                run_id=str(run_id),
                agent_id=agent_id,
                decisions=len(decision_ids),
                cost_usd=totals.cost_usd,
            )
            return {
                "run_id": str(run_id),
                "snapshot_id": str(snapshot_id),
                "decisions": decision_ids,
                "decision_rows": decision_rows,
                "cost_usd": totals.cost_usd,
                "tokens": {
                    "input": totals.input_tokens,
                    "output": totals.output_tokens,
                },
                "market_stance": parsed.market_stance,
                "regime_call": parsed.regime_call,
                "kind": kind,
            }

        except GuardRejectedError as exc:
            record_run_failure(agent_id, duration_seconds=time.perf_counter() - started)
            await self._finalize_guard_reject(run_id, agent_id, exc)
            raise GuardViolation(
                "guard_reject",
                f"guard REJECT after policy exhausted: {exc.violations}",
            ) from exc
        except GuardViolation:
            record_run_failure(agent_id, duration_seconds=time.perf_counter() - started)
            raise
        except Exception as exc:
            record_run_failure(agent_id, duration_seconds=time.perf_counter() - started)
            await self._mark_failed(run_id, str(exc))
            raise

    async def _llm_loop(
        self,
        *,
        llm: LLMClient,
        constitution: AgentConstitution,
        snapshot_id: UUID,
        snapshot_data: dict[str, Any],
        math_tool: MathTool,
        model: str,
        kind: str = "run",
        agent_messages: list[dict[str, Any]] | None = None,
        operator_context: dict[str, Any] | None = None,
        subordinate_reports: list[dict[str, Any]] | None = None,
    ) -> tuple[ParsedRunOutput, _TokenTotals, str, list[dict[str, str]]]:
        """Chat with optional tool calls, then return validated output."""
        is_rebuttal = kind == "rebuttal"
        is_rollup = kind == "rollup"
        allowed = set(constitution.tools)
        tools = (
            None
            if is_rebuttal or is_rollup
            else ([openai_tool_definition()] if "compute_stat" in allowed else None)
        )
        tool_calls_log: list[dict[str, str]] = []
        llm_snapshot = snapshot_for_llm(snapshot_data, kind=kind)
        user_payload: dict[str, Any] = {
            "snapshot_id": str(snapshot_id),
            "snapshot": llm_snapshot,
        }
        if operator_context:
            user_payload["operator_context"] = operator_context
        if is_rebuttal and agent_messages:
            user_payload["agent_messages"] = agent_messages
        if is_rollup and subordinate_reports:
            user_payload["subordinate_reports"] = subordinate_reports
        if is_rollup:
            user_intro = (
                "Synthesize the subordinate_reports below into your department briefing. "
                "Return ONLY valid JSON matching the output schema.\n\n"
            )
        elif is_rebuttal:
            user_intro = (
                "Rebut or affirm your prior stance using peer agent_messages below. "
                "Return ONLY valid JSON matching the output schema.\n\n"
            )
        else:
            user_intro = "Analyze the snapshot JSON below and return your decision object.\n\n"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": constitution.system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_intro}```json\n{json.dumps(user_payload, separators=(',', ':'))}\n```"
                ),
            },
        ]
        totals = _TokenTotals()
        raw_text = ""
        max_turns = 1 if is_rebuttal or is_rollup else max(1, constitution.max_turns)

        for turn in range(max_turns):
            is_final = turn >= max_turns - 1
            response = await llm.chat(
                model,
                messages,
                tools=None if is_final else tools,
                tool_choice="auto" if tools and not is_final else None,
                response_format={"type": "json_object"} if is_final else None,
                max_tokens=8192 if is_rollup else 4096,
                temperature=0.0,
                prompt_cache_key=f"agent-{constitution.agent_id}",
            )
            totals.input_tokens += response.usage.prompt_tokens
            totals.output_tokens += response.usage.completion_tokens
            totals.cost_usd += response.cost_usd

            if response.tool_calls and not is_final:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    },
                )
                for call in response.tool_calls:
                    fn = call.get("function") or {}
                    name = str(fn.get("name", ""))
                    if name not in allowed:
                        msg = f"Tool {name!r} is not whitelisted in constitution.tools"
                        raise ValueError(msg)
                    args_json = str(fn.get("arguments", "{}"))
                    tool_calls_log.append({"name": name, "arguments_json": args_json})
                    tool_result = await math_tool.handle_tool_call(args_json)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": tool_result,
                        },
                    )
                continue

            raw_text = _content_as_text(response.content)
            parsed_run = _parse_run_output(
                raw_text,
                constitution,
                kind=kind,
            )
            return parsed_run, totals, raw_text, tool_calls_log

        msg = "LLM loop exhausted max_turns without final JSON"
        raise RuntimeError(msg)

    async def _guard_until_pass(
        self,
        *,
        agent_id: str,
        run_id: str,
        constitution: AgentConstitution,
        llm: LLMClient,
        math_tool: MathTool,
        snapshot_id: UUID,
        snapshot_data: dict[str, Any],
        parsed: AgentOutput,
        raw_text: str,
        tool_calls: list[dict[str, str]],
        valid_symbols: set[str],
        primary_model: str,
        fallback_model: str | None,
        totals: _TokenTotals,
    ) -> AgentOutput:
        """Call guard-service until PASS or raise on REJECT (no agent_decisions on REJECT)."""
        current_parsed = parsed
        current_raw = raw_text
        used_fallback = False

        while True:
            result = await validate_agent_output(
                agent_id=agent_id,
                run_id=run_id,
                output=current_parsed,
                valid_symbols=valid_symbols,
                raw_text=current_raw,
                snapshot=snapshot_data,
                tool_calls=tool_calls,
            )
            if result.approved or result.outcome == "PASS":
                return current_parsed

            if result.outcome == "REJECT":
                log.warning("guard_reject_final", violations=result.violations, run_id=run_id)
                raise GuardRejectedError(result.violations)

            if result.outcome == "RETRY":
                log.warning("guard_outcome_retry", violations=result.violations, run_id=run_id)
                current_raw = await self._retry_llm(
                    llm=llm,
                    constitution=constitution,
                    math_tool=math_tool,
                    snapshot_id=snapshot_id,
                    snapshot_data=snapshot_data,
                    model=primary_model,
                    feedback=result.violations,
                    strict_prefix=result.sanitized_output,
                    totals=totals,
                )
                current_parsed_run = _parse_run_output(
                    current_raw,
                    constitution,
                    kind="run",
                )
                if current_parsed_run.mode != "trading" or current_parsed_run.trading is None:
                    raise GuardRejectedError(["guard_retry_produced_non_trading_output"])
                current_parsed = current_parsed_run.trading
                continue

            if result.outcome == "ESCALATE":
                if used_fallback or not fallback_model:
                    log.warning("guard_escalate_exhausted", run_id=run_id)
                    raise GuardRejectedError(result.violations)
                used_fallback = True
                log.warning("guard_outcome_escalate", model=fallback_model, run_id=run_id)
                current_raw = await self._retry_llm(
                    llm=llm,
                    constitution=constitution,
                    math_tool=math_tool,
                    snapshot_id=snapshot_id,
                    snapshot_data=snapshot_data,
                    model=fallback_model,
                    feedback=result.violations,
                    strict_prefix=result.sanitized_output,
                    totals=totals,
                )
                current_parsed_run = _parse_run_output(
                    current_raw,
                    constitution,
                    kind="run",
                )
                if current_parsed_run.mode != "trading" or current_parsed_run.trading is None:
                    raise GuardRejectedError(["guard_retry_produced_non_trading_output"])
                current_parsed = current_parsed_run.trading
                continue

            log.warning("guard_unknown_outcome", outcome=result.outcome)
            raise GuardRejectedError(result.violations)

    async def _retry_llm(
        self,
        *,
        llm: LLMClient,
        constitution: AgentConstitution,
        math_tool: MathTool,
        snapshot_id: UUID,
        snapshot_data: dict[str, Any],
        model: str,
        feedback: list[dict[str, str]],
        strict_prefix: str = "",
        totals: _TokenTotals,
    ) -> str:
        """Single retry LLM call with guard violation feedback (no tools)."""
        user_payload = {
            "snapshot_id": str(snapshot_id),
            "snapshot": snapshot_data,
            "guard_violations": feedback,
        }
        user_content = (
            f"{strict_prefix}"
            "Your prior output failed guard validation. Fix all violations and "
            "return ONLY valid JSON.\n\n"
            f"```json\n{json.dumps(user_payload, indent=2)}\n```"
        )
        messages = [
            {"role": "system", "content": constitution.system_prompt},
            {"role": "user", "content": user_content},
        ]
        _ = math_tool  # retry pass does not expose tools
        response = await llm.chat(
            model,
            messages,
            response_format={"type": "json_object"},
            max_tokens=4096,
            temperature=0.0,
        )
        totals.input_tokens += response.usage.prompt_tokens
        totals.output_tokens += response.usage.completion_tokens
        totals.cost_usd += response.cost_usd
        return _content_as_text(response.content)

    async def _persist_success(
        self,
        *,
        run_id: UUID,
        agent_id: str,
        snapshot_id: UUID,
        market: str,
        snapshot_data: dict[str, Any],
        parsed: AgentOutput,
        totals: _TokenTotals,
    ) -> list[str]:
        """Insert decisions and close the agent_runs row."""
        sym_to_id = {u["symbol"]: u["instrument_id"] for u in snapshot_data["universe"]}
        decision_ids: list[str] = []

        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            for d in parsed.decisions:
                iid = sym_to_id.get(d.instrument_symbol)
                evidence = {
                    "key_drivers": d.key_drivers,
                    "snapshot_id": str(snapshot_id),
                    "market_stance": parsed.market_stance,
                    "regime_call": parsed.regime_call,
                }
                cur = await conn.execute(
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
                row = await cur.fetchone()
                decision_ids.append(str(row[0]))

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
                    totals.input_tokens,
                    totals.output_tokens,
                    totals.cost_usd,
                    run_id,
                ),
            )
            await conn.commit()

        return decision_ids

    async def _persist_briefing_success(
        self,
        *,
        run_id: UUID,
        totals: _TokenTotals,
    ) -> None:
        """Close a briefing run without inserting instrument decisions."""
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
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
                    totals.input_tokens,
                    totals.output_tokens,
                    totals.cost_usd,
                    run_id,
                ),
            )
            await conn.commit()

    async def _finalize_guard_reject(
        self,
        run_id: UUID,
        agent_id: str,
        rejected: GuardRejectedError,
    ) -> None:
        """Close run without inserting agent_decisions (guard_violations only)."""
        detail = json.dumps({"violations": rejected.violations})[:500]
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                """
                UPDATE theeyebeta.agent_runs
                   SET status = 'failed',
                       ended_at = now(),
                       error = %s
                 WHERE id = %s
                """,
                (f"guard_reject: {detail}", run_id),
            )
            await conn.commit()
        log.info(
            "agent_run_guard_rejected",
            run_id=str(run_id),
            agent_id=agent_id,
            violations=len(rejected.violations),
        )

    async def _mark_failed(self, run_id: UUID, error: str) -> None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await conn.execute(
                """
                UPDATE theeyebeta.agent_runs
                   SET status = 'failed', ended_at = now(), error = %s
                 WHERE id = %s
                """,
                (error[:500], run_id),
            )
            await conn.commit()

    async def _publish_decision_event(
        self,
        agent_id: str,
        run_id: UUID,
        parsed: AgentOutput,
        decision_ids: list[str],
    ) -> None:
        """Publish ``agents.decisions.{agent_id}`` on NATS."""
        nats_url = os.environ.get("NATS_URL", "nats://127.0.0.1:4222")
        subject = f"agents.decisions.{agent_id}"
        payload = json.dumps(
            {
                "run_id": str(run_id),
                "agent_id": agent_id,
                "decision_ids": decision_ids,
                "market_stance": parsed.market_stance,
                "regime_call": parsed.regime_call,
                "decisions": [d.model_dump() for d in parsed.decisions],
            },
        ).encode()
        nc = await nats.connect(nats_url)
        try:
            await nc.publish(subject, payload)
            log.info("agent_decision_published", subject=subject, run_id=str(run_id))
        finally:
            await nc.close()


def _content_as_text(content: str | dict[str, Any] | list[Any] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content)


def _expects_trading_output(constitution: AgentConstitution, kind: str) -> bool:
    """Return True when the agent must emit market_stance/regime_call/decisions."""
    if kind == "rollup":
        return False
    body = constitution.system_prompt
    if "Same contract as other market agents" in body:
        return True
    return (
        "market_stance" in body
        and "regime_call" in body
        and "decisions" in body
        and "instrument_symbol" in body
    )


def _briefing_summary_fields(briefing: dict[str, Any]) -> tuple[str, str]:
    """Map heterogeneous briefing JSON to API stance/regime fields."""
    stance_raw = (
        briefing.get("market_stance")
        or briefing.get("outcome")
        or briefing.get("decision")
        or briefing.get("verdict")
        or "neutral"
    )
    regime_raw = briefing.get("regime_call") or briefing.get("regime") or "ranging"
    stance = str(stance_raw).lower()
    regime = str(regime_raw).lower()
    if stance not in {"bullish", "bearish", "neutral"}:
        stance = "neutral"
    if regime not in {"trending", "ranging", "volatile", "calm"}:
        regime = "ranging"
    return stance, regime


def _parse_run_output(
    raw_text: str,
    constitution: AgentConstitution,
    *,
    kind: str,
) -> ParsedRunOutput:
    """Parse LLM JSON as trading decisions or a department briefing."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise GuardViolation("schema_invalid_json", str(exc)) from exc
    if not isinstance(payload, dict):
        raise GuardViolation("schema_invalid_json", "Output must be a JSON object")

    if _expects_trading_output(constitution, kind):
        try:
            trading = AgentOutput.model_validate(payload)
        except ValidationError as exc:
            log.warning(
                "trading_schema_fallback_to_briefing",
                agent_id=constitution.agent_id,
                error=str(exc),
            )
            return ParsedRunOutput(mode="briefing", briefing=payload)
        return ParsedRunOutput(mode="trading", trading=trading)
    return ParsedRunOutput(mode="briefing", briefing=payload)


def _parse_output(raw_text: str, schema_version: int) -> AgentOutput:
    if schema_version != 1:
        msg = f"Unsupported output_schema_version: {schema_version}"
        raise ValueError(msg)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise GuardViolation("schema_invalid_json", str(exc)) from exc
    try:
        return AgentOutput.model_validate(payload)
    except ValidationError as exc:
        raise GuardViolation("schema_pydantic", str(exc)) from exc


def _escalate_observe(parsed: AgentOutput, valid_symbols: set[str]) -> AgentOutput:
    """Force OBSERVE on every symbol when guard cannot be satisfied."""
    decisions: list[AgentDecision] = []
    seen = {d.instrument_symbol for d in parsed.decisions}
    for symbol in sorted(valid_symbols):
        if symbol in seen:
            continue
        decisions.append(
            AgentDecision(
                instrument_symbol=symbol,
                decision="OBSERVE",
                confidence=0.5,
                horizon_days=5,
                key_drivers=["guard_escalation: insufficient evidence"],
                rationale=(
                    f"technicals.{symbol}.rsi14 unavailable; guard validation failed — OBSERVE."
                ),
            ),
        )
    for d in parsed.decisions:
        decisions.append(
            AgentDecision(
                instrument_symbol=d.instrument_symbol,
                decision="OBSERVE",
                confidence=min(d.confidence, 0.5),
                horizon_days=d.horizon_days,
                key_drivers=d.key_drivers + ["guard_escalation"],
                rationale=f"Guard escalation: {d.rationale[:1200]}",
            ),
        )
    return AgentOutput(
        market_stance="neutral",
        regime_call="ranging",
        decisions=decisions,
    )


async def run_agent(agent_id: str, market: str, trade_date: str) -> dict[str, Any]:
    """CLI helper: resolve latest packaged snapshot for market+date, then run.

    Args:
        agent_id: Agent identifier.
        market: Market code (e.g. ``US``).
        trade_date: ISO date string.

    Returns:
        Run summary from :meth:`AgentRunner.run`.
    """
    from datetime import date

    trade = date.fromisoformat(trade_date)
    async with await psycopg.AsyncConnection.connect(_db_url()) as conn:
        cur = await conn.execute(
            """
            SELECT snapshot_id
              FROM theeyebeta.data_snapshots_packaged
             WHERE market = %s AND trade_date = %s
             ORDER BY packaged_at DESC
             LIMIT 1
            """,
            (market.upper(), trade),
        )
        row = await cur.fetchone()
    if not row:
        raise ValueError(f"No packaged snapshot for {market} on {trade_date}")
    snapshot_id = row[0]
    runner = AgentRunner()
    return await runner.run(agent_id, snapshot_id)
