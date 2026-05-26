"""HTTP clients for executor agents and validation services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import structlog

from master_orchestrator.models import AgentDecisionView, AgentRunResult, TradeTicket

log = structlog.get_logger()


class AgentRuntimeClient:
    """Client for agent-runtime POST /agents/{id}/run."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def run_agent(
        self,
        agent_id: str,
        snapshot_id: UUID | str,
        *,
        kind: str = "run",
        agent_messages: list[dict[str, str]] | None = None,
    ) -> AgentRunResult:
        """Spawn one agent run and return structured decisions."""
        payload: dict[str, Any] = {
            "snapshot_id": str(snapshot_id),
            "kind": kind,
            "agent_messages": agent_messages or [],
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/agents/{agent_id}/run",
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        decisions: list[AgentDecisionView] = []
        for row in body.get("decision_rows") or []:
            decisions.append(
                AgentDecisionView(
                    agent_id=agent_id,
                    run_id=body["run_id"],
                    decision_id=row.get("decision_id"),
                    instrument_symbol=row["instrument_symbol"],
                    instrument_id=row.get("instrument_id"),
                    decision=row["decision"],
                    confidence=float(row["confidence"]),
                    horizon_days=int(row["horizon_days"]),
                    rationale=row["rationale"],
                    key_drivers=list(row.get("key_drivers") or []),
                ),
            )
        return AgentRunResult(
            agent_id=agent_id,
            run_id=body["run_id"],
            snapshot_id=body["snapshot_id"],
            market_stance=body["market_stance"],
            regime_call=body["regime_call"],
            decisions=decisions,
        )


class RiskServiceClient:
    """Validate tickets against risk-service (optional)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""

    async def validate(self, ticket: TradeTicket, *, portfolio_id: str) -> None:
        """Raise when risk-service blocks the ticket."""
        if not self._base_url:
            log.debug("risk_service_skipped", reason="RISK_SERVICE_URL unset")
            return
        payload = {
            "portfolio_id": portfolio_id,
            "instrument_id": ticket.instrument_id,
            "side": ticket.side,
            "qty": ticket.qty,
            "market": ticket.market,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self._base_url}/v1/validate-order", json=payload)
            response.raise_for_status()
            body = response.json()
        if not body.get("approved", True):
            msg = f"risk-service rejected ticket: {body.get('detail', body)}"
            raise ValueError(msg)

    async def compute_portfolio_metrics(self, portfolio_id: str) -> dict[str, object]:
        """Trigger risk-service portfolio metric recompute."""
        if not self._base_url:
            log.debug("risk_metrics_skipped", reason="RISK_SERVICE_URL unset")
            return {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/compute-portfolio-metrics",
                json={"portfolio_id": portfolio_id},
            )
            response.raise_for_status()
            return response.json()


class ComplianceServiceClient:
    """Validate tickets against compliance-service (optional)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/") if base_url else ""

    async def validate(self, ticket: TradeTicket, *, portfolio_id: str) -> None:
        """Raise when compliance-service blocks the ticket."""
        if not self._base_url:
            log.debug("compliance_service_skipped", reason="COMPLIANCE_SERVICE_URL unset")
            return
        payload = {
            "portfolio_id": portfolio_id,
            "instrument_id": ticket.instrument_id,
            "side": ticket.side,
            "qty": ticket.qty,
            "market": ticket.market,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{self._base_url}/v1/validate-order", json=payload)
            response.raise_for_status()
            body = response.json()
        if not body.get("approved", True):
            msg = f"compliance-service rejected ticket: {body.get('detail', body)}"
            raise ValueError(msg)
