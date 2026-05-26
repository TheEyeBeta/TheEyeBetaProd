"""Bounded debate rounds between executor agents."""

from __future__ import annotations

from uuid import UUID

import structlog

from master_orchestrator.clients import AgentRuntimeClient
from master_orchestrator.disagreement import decisions_disagree
from master_orchestrator.models import AgentRunResult, DebateEntry, DebateTranscript
from master_orchestrator.observability import record_debate_round

log = structlog.get_logger()

MAX_DEBATE_ROUNDS = 2


class DebateRound:
    """Run up to two rebuttal rounds across the market trio."""

    def __init__(self, agent_client: AgentRuntimeClient) -> None:
        self._agent_client = agent_client

    async def run(
        self,
        results: list[AgentRunResult],
        snapshot_id: UUID | str,
        *,
        market: str = "US",
    ) -> DebateTranscript:
        """Each agent rebutts peers once per round (bounded at two rounds).

        Args:
            results: Initial executor agent outputs.
            snapshot_id: Packaged snapshot UUID shared by all agents.

        Returns:
            Transcript with rebuttal entries and final agent results.
        """
        current = list(results)
        transcript: list[DebateEntry] = []

        for round_num in range(1, MAX_DEBATE_ROUNDS + 1):
            if not decisions_disagree(current):
                log.info("debate_resolved_early", round_num=round_num)
                break

            next_round: list[AgentRunResult] = []
            for agent_result in current:
                peers = [r for r in current if r.agent_id != agent_result.agent_id]
                agent_messages = [
                    {
                        "agent_id": peer.agent_id,
                        "instrument_symbol": d.instrument_symbol,
                        "decision": d.decision,
                        "rationale": d.rationale,
                    }
                    for peer in peers
                    for d in peer.decisions
                ]
                rebuttal = await self._agent_client.run_agent(
                    agent_result.agent_id,
                    snapshot_id,
                    kind="rebuttal",
                    agent_messages=agent_messages,
                )
                transcript.append(
                    DebateEntry(
                        round_num=round_num,
                        agent_id=agent_result.agent_id,
                        run_id=rebuttal.run_id,
                        peer_agent_ids=[p.agent_id for p in peers],
                        decisions=rebuttal.decisions,
                    ),
                )
                next_round.append(rebuttal)

            current = next_round
            record_debate_round(market, round_num)
            if not decisions_disagree(current):
                log.info("debate_resolved", round_num=round_num)
                break

        return DebateTranscript(rounds=transcript, final_results=current)
