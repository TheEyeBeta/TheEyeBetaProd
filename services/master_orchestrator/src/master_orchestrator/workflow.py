"""Market trio workflow — spawn agents, debate, synthesize ticket."""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

import structlog

from master_orchestrator.clients import (
    AgentRuntimeClient,
    ComplianceServiceClient,
    RiskServiceClient,
)
from master_orchestrator.db import (
    insert_pending_order,
    publish_order_proposed,
    resolve_portfolio_id,
)
from master_orchestrator.debate import DebateRound
from master_orchestrator.disagreement import decisions_disagree
from master_orchestrator.idempotency import TrioIdempotencyLock
from master_orchestrator.models import AgentRunResult, DebateTranscript, WorkflowResult
from master_orchestrator.observability import observe_trio_duration, record_trio_outcome
from master_orchestrator.settings import Settings
from master_orchestrator.synthesis import TicketSynthesizer

log = structlog.get_logger()

MARKET_TRIO_AGENTS: dict[str, list[str]] = {
    "US": ["macro-lead", "news-sentiment", "technical-analyst"],
    "HK": ["macro-lead", "news-sentiment", "technical-analyst"],
    "JP": ["macro-lead", "news-sentiment", "technical-analyst"],
    "TW": ["macro-lead", "news-sentiment", "technical-analyst"],
    "CN": ["macro-lead", "news-sentiment", "technical-analyst"],
}

DEFAULT_TRIO = ["macro-lead", "news-sentiment", "technical-analyst"]


def agents_for_market(market: str) -> list[str]:
    """Return the executor trio for a market."""
    return MARKET_TRIO_AGENTS.get(market.upper(), DEFAULT_TRIO)


def _parse_trade_date(trade_date: date | str | None) -> date | None:
    if trade_date is None:
        return None
    if isinstance(trade_date, date):
        return trade_date
    return date.fromisoformat(trade_date)


class MarketTrioWorkflow:
    """Orchestrate executor agents, optional debate, and order synthesis."""

    def __init__(
        self,
        settings: Settings,
        *,
        idempotency: TrioIdempotencyLock | None = None,
    ) -> None:
        self._settings = settings
        self._agent_client = AgentRuntimeClient(settings.agent_runtime_url)
        self._debate = DebateRound(self._agent_client)
        self._risk = RiskServiceClient(settings.risk_service_url)
        self._compliance = ComplianceServiceClient(settings.compliance_service_url)
        self._synthesizer = TicketSynthesizer(
            virtual_key=settings.llm_virtual_key,
            base_url=settings.llm_proxy_url,
            default_qty=settings.default_order_qty,
        )
        self._idempotency = idempotency or TrioIdempotencyLock()

    async def run(
        self,
        market: str,
        snapshot_id: UUID | str,
        *,
        trade_date: date | str | None = None,
    ) -> WorkflowResult:
        """Execute the full market-trio workflow for one packaged snapshot."""
        market = market.upper()
        snapshot_uuid = UUID(str(snapshot_id))
        parsed_date = _parse_trade_date(trade_date)

        if parsed_date is not None and not await self._idempotency.try_acquire(
            market,
            parsed_date,
        ):
            record_trio_outcome(market, "skipped")
            return WorkflowResult(
                market=market,
                snapshot_id=str(snapshot_uuid),
                trade_date=parsed_date.isoformat(),
                debated=False,
                skipped=True,
                outcome="skipped",
            )

        with observe_trio_duration(market):
            try:
                return await self._run_inner(market, snapshot_uuid, parsed_date)
            except Exception:
                if parsed_date is not None:
                    await self._idempotency.release(market, parsed_date)
                raise

    async def _run_inner(
        self,
        market: str,
        snapshot_uuid: UUID,
        trade_date: date | None,
    ) -> WorkflowResult:
        agent_ids = agents_for_market(market)
        log.info(
            "market_trio_started",
            market=market,
            snapshot_id=str(snapshot_uuid),
            trade_date=str(trade_date) if trade_date else None,
            agents=agent_ids,
        )

        results = await self._spawn_agents(agent_ids, snapshot_uuid)
        debated = False
        transcript: DebateTranscript | None = None
        final_results = results

        if decisions_disagree(results):
            log.info("market_trio_debate_triggered", market=market)
            debated = True
            transcript = await self._debate.run(results, snapshot_uuid, market=market)
            final_results = transcript.final_results

        default_instrument_id = _default_instrument_id(final_results)
        try:
            ticket = await self._synthesizer.synthesize(
                market=market,
                agent_results=final_results,
                transcript=transcript,
                default_instrument_id=default_instrument_id,
            )
        except ValueError as exc:
            log.warning("market_trio_no_decision", market=market, error=str(exc))
            record_trio_outcome(market, "no-decision")
            if trade_date is not None:
                await self._idempotency.release(market, trade_date)
            return WorkflowResult(
                market=market,
                snapshot_id=str(snapshot_uuid),
                trade_date=trade_date.isoformat() if trade_date else None,
                debated=debated,
                outcome="no-decision",
                transcript=transcript,
                agent_results=final_results,
                metadata={"error": str(exc)},
            )

        dsn = self._settings.pg_dsn()
        portfolio_id = await resolve_portfolio_id(self._settings.default_portfolio_id, dsn)
        await self._risk.validate(ticket, portfolio_id=str(portfolio_id))
        await self._compliance.validate(ticket, portfolio_id=str(portfolio_id))

        order_id = await insert_pending_order(dsn=dsn, portfolio_id=portfolio_id, ticket=ticket)
        await publish_order_proposed(order_id, ticket)

        outcome = "debate" if debated else "consensus"
        record_trio_outcome(market, outcome)
        if trade_date is not None:
            await self._idempotency.mark_complete(market, trade_date, str(order_id))

        log.info(
            "market_trio_completed",
            market=market,
            snapshot_id=str(snapshot_uuid),
            order_id=str(order_id),
            debated=debated,
            outcome=outcome,
        )
        return WorkflowResult(
            market=market,
            snapshot_id=str(snapshot_uuid),
            trade_date=trade_date.isoformat() if trade_date else None,
            debated=debated,
            order_id=str(order_id),
            outcome=outcome,
            ticket=ticket,
            transcript=transcript,
            agent_results=final_results,
        )

    async def _spawn_agents(
        self,
        agent_ids: list[str],
        snapshot_id: UUID,
    ) -> list[AgentRunResult]:
        """Run all trio agents in parallel."""
        tasks = [
            self._agent_client.run_agent(agent_id, snapshot_id, kind="run")
            for agent_id in agent_ids
        ]
        return list(await asyncio.gather(*tasks))


def _default_instrument_id(results: list[AgentRunResult]) -> int | None:
    for result in results:
        for decision in result.decisions:
            if decision.instrument_id is not None:
                return decision.instrument_id
    return None
