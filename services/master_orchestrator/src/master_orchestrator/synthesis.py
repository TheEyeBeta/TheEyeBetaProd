"""Master orchestrator synthesis — GPT-5 ticket generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from master_orchestrator.models import AgentRunResult, DebateTranscript, TradeTicket
from zinc_schemas.constitution import load_constitution, resolve_agents_dir
from zinc_schemas.llm_client import LLMClient

log = structlog.get_logger()

_SYNTHESIS_MODEL = "gpt-5"
_PROMPT_CACHE_KEY = "master-orchestrator-synthesis-v1"


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _load_system_prompt() -> str:
    repo_root = Path(__file__).resolve().parents[4]
    constitution_path = resolve_agents_dir(repo_root) / "master-orchestrator.md"
    if constitution_path.is_file():
        return load_constitution(constitution_path).system_prompt
    return (
        "You are the master orchestrator. Synthesize executor agent decisions into "
        "one trade ticket JSON with keys: market, instrument_id, side (buy|sell), "
        "qty, horizon_days, rationale_summary. Output ONLY JSON."
    )


def _decision_id_for_ticket(
    agent_results: list[AgentRunResult],
    ticket: TradeTicket,
) -> UUID | None:
    """Match a synthesized ticket back to the agent decision it came from.

    The LLM synthesis prompt never asks for ``decision_id`` (only market,
    instrument_id, side, qty, horizon_days, rationale_summary), so the real
    LLM path always returns it as None. Backfill it here from the underlying
    agent decisions so ``theeyebeta.orders.decision_id`` stays traceable.
    """
    from master_orchestrator.disagreement import decision_rank

    wants_buy = ticket.side == "buy"
    for result in agent_results:
        for decision in result.decisions:
            if decision.instrument_id != ticket.instrument_id or not decision.decision_id:
                continue
            rank = decision_rank(decision.decision)
            if rank == 0:
                continue
            if (rank > 0) == wants_buy:
                return UUID(decision.decision_id)
    return None


class TicketSynthesizer:
    """Call the master orchestrator LLM to produce a validated ticket."""

    def __init__(
        self,
        *,
        virtual_key: str,
        base_url: str,
        default_qty: float,
    ) -> None:
        self._virtual_key = virtual_key
        self._base_url = base_url.rstrip("/")
        self._default_qty = default_qty
        self._system_prompt = _load_system_prompt()

    async def synthesize(
        self,
        *,
        market: str,
        agent_results: list[AgentRunResult],
        transcript: DebateTranscript | None,
        default_instrument_id: int | None = None,
    ) -> TradeTicket:
        """Produce a trade ticket from agent outputs and optional debate transcript."""
        payload: dict[str, Any] = {
            "market": market,
            "agent_results": [r.model_dump() for r in agent_results],
            "debate_transcript": transcript.model_dump() if transcript else None,
            "default_qty": self._default_qty,
            "default_instrument_id": default_instrument_id,
        }
        if self._virtual_key.startswith("sk-"):
            ticket = await self._synthesize_llm(payload)
        else:
            log.warning("synthesis_fallback_heuristic", reason="missing LITELLM key")
            ticket = self._synthesize_heuristic(market, agent_results, default_instrument_id)
        if ticket.decision_id is None:
            matched = _decision_id_for_ticket(agent_results, ticket)
            if matched is not None:
                ticket = ticket.model_copy(update={"decision_id": matched})
        return ticket

    async def _synthesize_llm(self, payload: dict[str, Any]) -> TradeTicket:
        messages = [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": (
                    "Synthesize the following agent outputs into one trade ticket JSON.\n\n"
                    f"```json\n{json.dumps(payload, indent=2)}\n```"
                ),
            },
        ]
        async with LLMClient(
            self._virtual_key,
            self._base_url,
            database_url=None,
        ) as llm:
            response = await llm.chat(
                _SYNTHESIS_MODEL,
                messages,
                max_tokens=512,
                temperature=0.0,
                response_format={"type": "json_object"},
                prompt_cache_key=_PROMPT_CACHE_KEY,
            )
        raw = _strip_fences(str(response.content or ""))
        data = json.loads(raw)
        return TradeTicket.model_validate(data)

    def _synthesize_heuristic(
        self,
        market: str,
        agent_results: list[AgentRunResult],
        default_instrument_id: int | None,
    ) -> TradeTicket:
        """Deterministic fallback when LLM key is unavailable (tests/dev)."""
        from master_orchestrator.disagreement import decision_rank

        best: tuple[int, float, Any] | None = None
        for result in agent_results:
            for decision in result.decisions:
                rank = decision_rank(decision.decision)
                if rank == 0:
                    continue
                score = abs(rank) * decision.confidence
                if best is None or score > best[0]:
                    best = (score, decision.confidence, decision)

        if best is None:
            msg = "no actionable decisions to synthesize"
            raise ValueError(msg)

        _, _, decision = best
        side = "buy" if decision_rank(decision.decision) > 0 else "sell"
        instrument_id = decision.instrument_id or default_instrument_id
        if instrument_id is None:
            msg = "instrument_id missing from agent decisions"
            raise ValueError(msg)

        return TradeTicket(
            market=market,
            instrument_id=int(instrument_id),
            side=side,
            qty=self._default_qty,
            horizon_days=decision.horizon_days,
            rationale_summary=decision.rationale[:2000],
            decision_id=UUID(decision.decision_id) if decision.decision_id else None,
        )
