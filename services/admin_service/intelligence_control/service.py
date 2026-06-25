"""Intelligence layer orchestration."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import structlog
from api.backtest import _engine_url, _raise_for_engine_status, _row_to_summary
from api.costs import current_month_key, fetch_costs_by_agent, fetch_costs_by_vendor, fetch_daily_costs
from audit_log import write_audit_log
from fastapi import HTTPException
from intelligence_control.registry import (
    AGENT_CONFIG_FILE_GAP,
    BACKTEST_CANCEL_GAP,
    BACKTEST_RETRY_GAP,
    BRIEFING_GENERATION_GAP,
    CONFIG_PATCH_GAP,
    REPORT_REGENERATE_GAP,
    ROLLBACK_PROPOSAL_GAP,
    IntelligenceControlGap,
)
from intelligence_control.repository import IntelligenceRepository
from settings import Settings
from zinc_schemas.admin_dto import (
    AgentConfigPatchRequest,
    AgentConfigPatchResponse,
    AgentDetailResponse,
    AgentDisableResponse,
    AgentPauseResponse,
    AgentRollbackResponse,
    AgentVersionEntry,
    AgentVersionsResponse,
    BacktestArtifactsResponse,
    BacktestArtifactEntry,
    BacktestCancelResponse,
    BacktestDetailResponse,
    BacktestRetryResponse,
    CostsBudgetEntry,
    CostsBudgetPatchRequest,
    CostsBudgetsResponse,
    CostsKillSwitchRequest,
    CostsKillSwitchResponse,
    CostsOverviewResponse,
    IntelligenceControlGapEntry,
    ProposalActionResponse,
    ReportBriefingEntry,
    ReportExportResponse,
    ReportListResponse,
    ReportRegenerateRequest,
    ReportRegenerateResponse,
    StartBacktestRequest,
)

log = structlog.get_logger()


class IntelligenceControlService:
    """Agents, proposals, backtests, reports, and costs control."""

    def __init__(self, conn: Any, settings: Settings) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = IntelligenceRepository(conn)

    def _gaps(self, *extra: IntelligenceControlGap) -> list[IntelligenceControlGapEntry]:
        base = [CONFIG_PATCH_GAP, ROLLBACK_PROPOSAL_GAP, REPORT_REGENERATE_GAP]
        return [
            IntelligenceControlGapEntry(action=g.action, reason=g.reason)
            for g in [*base, *extra]
        ]

    async def get_agent_detail(self, agent_id: str) -> AgentDetailResponse:
        from api.agents import fetch_agents_summary  # noqa: PLC0415 — avoid circular import

        row = await self._repo.agent_row(agent_id)
        if row is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        agents = await fetch_agents_summary(self._conn)
        summary = next((a for a in agents if a.id == agent_id), None)
        violations = await self._repo.agent_violation_count(agent_id)
        cost_7d = await self._repo.agent_cost_7d(agent_id)
        return AgentDetailResponse(
            id=row["id"],
            department=row["department"],
            role=row["role"],
            model_default=row["model_default"],
            model_fallback=row["model_fallback"],
            constitution_path=row["constitution_path"],
            active=bool(row["active"]),
            paused=bool(row["paused"]),
            last_run_at=summary.last_run_at if summary else None,
            runs_7d=summary.runs_7d if summary else 0,
            success_rate_7d=summary.success_rate_7d if summary else None,
            open_violation_count=violations,
            cost_7d_usd=cost_7d,
            control_gaps=self._gaps(),
        )

    async def pause_agent(self, agent_id: str, *, actor: str, reason: str) -> AgentPauseResponse:
        if await self._repo.agent_row(agent_id) is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        await self._repo.set_agent_paused(agent_id, paused=True, actor=actor)
        await self._repo.record_event(
            event_type="agent_pause",
            actor=actor,
            reason=reason,
            payload={"agent_id": agent_id},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="agent.pause",
            entity_type="agent",
            entity_id=agent_id,
            payload={"reason": reason},
        )
        return AgentPauseResponse(agent_id=agent_id, paused=True, audited=True, reason=reason)

    async def disable_agent(self, agent_id: str, *, actor: str, reason: str) -> AgentDisableResponse:
        if await self._repo.agent_row(agent_id) is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        await self._repo.set_agent_active(agent_id, active=False)
        await self._repo.set_agent_paused(agent_id, paused=True, actor=actor)
        await self._repo.record_event(
            event_type="agent_disable",
            actor=actor,
            reason=reason,
            payload={"agent_id": agent_id},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="agent.disable",
            entity_type="agent",
            entity_id=agent_id,
            payload={"reason": reason},
        )
        return AgentDisableResponse(agent_id=agent_id, active=False, audited=True, reason=reason)

    async def patch_agent_config(
        self,
        agent_id: str,
        body: AgentConfigPatchRequest,
        *,
        actor: str,
    ) -> AgentConfigPatchResponse:
        if body.model_default is None and body.model_fallback is None:
            msg = "At least one of model_default or model_fallback required"
            raise ValueError(msg)
        row = await self._repo.patch_agent_models(
            agent_id,
            model_default=body.model_default,
            model_fallback=body.model_fallback,
        )
        if row is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        from api.agents import read_agent_constitution  # noqa: PLC0415

        constitution = await read_agent_constitution(
            self._conn,
            self._settings.repo_root_path(),
            agent_id,
        )
        await self._repo.insert_agent_version(
            agent_id=agent_id,
            label=f"pre-patch-{IntelligenceRepository.utc_now().isoformat()}",
            constitution_path=constitution.constitution_path,
            content=constitution.content,
            actor=actor,
        )
        await self._repo.record_event(
            event_type="agent_config_patch",
            actor=actor,
            reason=body.reason,
            payload={"agent_id": agent_id},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="agent.config.patch",
            entity_type="agent",
            entity_id=agent_id,
            payload=body.model_dump(mode="json"),
        )
        return AgentConfigPatchResponse(
            agent_id=agent_id,
            model_default=row["model_default"],
            model_fallback=row["model_fallback"],
            audited=True,
            reason=body.reason,
        )

    async def list_agent_versions(self, agent_id: str) -> AgentVersionsResponse:
        if await self._repo.agent_row(agent_id) is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        rows = await self._repo.list_agent_versions(agent_id)
        return AgentVersionsResponse(
            agent_id=agent_id,
            versions=[
                AgentVersionEntry(
                    id=row["id"],
                    label=str(row["label"]),
                    constitution_path=str(row["constitution_path"]),
                    content_hash=row.get("content_hash"),
                    created_at=row["created_at"],
                    created_by=str(row["created_by"]),
                )
                for row in rows
            ],
        )

    async def rollback_agent_version(
        self,
        agent_id: str,
        version_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> AgentRollbackResponse:
        version = await self._repo.get_agent_version(agent_id, version_id)
        if version is None:
            msg = f"Version {version_id} not found for agent {agent_id}"
            raise ValueError(msg)
        agent = await self._repo.agent_row(agent_id)
        if agent is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        target = Path(agent["constitution_path"])
        if not target.is_absolute():
            target = self._settings.repo_root_path() / target
        note = AGENT_CONFIG_FILE_GAP
        await self._repo.record_event(
            event_type="agent_rollback",
            actor=actor,
            reason=reason,
            payload={"agent_id": agent_id, "version_id": str(version_id), "path": str(target)},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="agent.rollback",
            entity_type="agent",
            entity_id=agent_id,
            payload={"version_id": str(version_id), "reason": reason},
        )
        return AgentRollbackResponse(
            agent_id=agent_id,
            version_id=version_id,
            constitution_path=str(version["constitution_path"]),
            mode="recorded",
            audited=True,
            reason=reason,
            notes=note,
        )

    async def defer_proposal(self, proposal_id: UUID, *, actor: str, reason: str) -> ProposalActionResponse:
        row = await self._repo.defer_proposal(proposal_id, actor=actor, note=reason)
        if row is None:
            msg = "Proposal not found or not pending"
            raise ValueError(msg)
        await self._audit_proposal("proposal.defer", proposal_id, actor, reason)
        return ProposalActionResponse(
            id=row["id"],
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            audited=True,
            reason=reason,
        )

    async def supersede_proposal(
        self,
        proposal_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> ProposalActionResponse:
        row = await self._repo.supersede_proposal(proposal_id, actor=actor, note=reason)
        if row is None:
            msg = "Proposal not found or not deferrable"
            raise ValueError(msg)
        await self._audit_proposal("proposal.supersede", proposal_id, actor, reason)
        return ProposalActionResponse(
            id=row["id"],
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            audited=True,
            reason=reason,
        )

    async def rollback_proposal(
        self,
        proposal_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> ProposalActionResponse:
        row = await self._repo.rollback_proposal(proposal_id, actor=actor, note=reason)
        if row is None:
            msg = "Proposal not found or not rollback-eligible"
            raise ValueError(msg)
        await self._audit_proposal("proposal.rollback", proposal_id, actor, reason)
        return ProposalActionResponse(
            id=row["id"],
            status=row["status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            audited=True,
            reason=reason,
        )

    async def _audit_proposal(
        self,
        action: str,
        proposal_id: UUID,
        actor: str,
        reason: str,
    ) -> None:
        await self._repo.record_event(
            event_type=action.split(".")[-1],
            actor=actor,
            reason=reason,
            payload={"proposal_id": str(proposal_id)},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action=action,
            entity_type="proposal",
            entity_id=str(proposal_id),
            payload={"reason": reason},
        )

    async def get_backtest_detail(self, backtest_id: UUID) -> BacktestDetailResponse:
        row = await self._repo.backtest_row(backtest_id)
        if row is None:
            msg = f"Backtest {backtest_id} not found"
            raise ValueError(msg)
        summary = _row_to_summary(row)
        return BacktestDetailResponse(
            **summary.model_dump(),
            control_gaps=[
                IntelligenceControlGapEntry(action="cancel", reason=BACKTEST_CANCEL_GAP),
                IntelligenceControlGapEntry(action="retry", reason=BACKTEST_RETRY_GAP),
            ],
        )

    async def cancel_backtest(self, backtest_id: UUID, *, actor: str, reason: str) -> BacktestCancelResponse:
        row = await self._repo.cancel_backtest(backtest_id)
        if row is None:
            msg = "Backtest not found or not cancellable"
            raise ValueError(msg)
        await self._repo.record_event(
            event_type="backtest_cancel",
            actor=actor,
            reason=reason,
            payload={"backtest_id": str(backtest_id)},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="backtest.cancel",
            entity_type="backtest_run",
            entity_id=str(backtest_id),
            payload={"reason": reason, "mode": "db_only"},
        )
        return BacktestCancelResponse(
            id=row["id"],
            status=row["status"],
            mode="db_only",
            audited=True,
            reason=reason,
        )

    async def retry_backtest(
        self,
        backtest_id: UUID,
        *,
        actor: str,
        reason: str,
    ) -> BacktestRetryResponse:
        row = await self._repo.backtest_row(backtest_id)
        if row is None:
            msg = f"Backtest {backtest_id} not found"
            raise ValueError(msg)
        body = StartBacktestRequest(
            strategy_id=row["strategy_id"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            universe=row["universe"],
        )
        url = _engine_url(self._settings, "/backtest/run")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=body.model_dump(mode="json"))
        except httpx.HTTPError as exc:
            msg = "backtest-engine unreachable"
            raise ValueError(msg) from exc
        try:
            _raise_for_engine_status(response)
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc
        data = response.json()
        new_id = str(data.get("backtest_run_id") or "")
        await write_audit_log(
            self._conn,
            actor=actor,
            action="backtest.retry",
            entity_type="backtest_run",
            entity_id=new_id,
            payload={"reason": reason, "source_id": str(backtest_id)},
        )
        return BacktestRetryResponse(
            source_id=backtest_id,
            new_backtest_run_id=UUID(new_id),
            status=str(data.get("status") or "running"),
            audited=True,
            reason=reason,
        )

    async def backtest_artifacts(self, backtest_id: UUID) -> BacktestArtifactsResponse:
        row = await self._repo.backtest_row(backtest_id)
        if row is None:
            msg = f"Backtest {backtest_id} not found"
            raise ValueError(msg)
        artifacts: list[dict[str, str | None]] = []
        if row["result_blob_uri"]:
            artifacts.append({"kind": "result_blob", "uri": row["result_blob_uri"]})
        return BacktestArtifactsResponse(
            backtest_run_id=backtest_id,
            artifacts=[
                BacktestArtifactEntry(kind=str(item["kind"]), uri=str(item["uri"]))
                for item in artifacts
            ],
        )

    async def list_reports(self, *, limit: int = 50) -> ReportListResponse:
        await self._repo.mark_briefings_stale()
        rows = await self._repo.list_briefings(limit=limit)
        stale = [r for r in rows if r["status"] == "stale"]
        return ReportListResponse(
            briefings=[
                ReportBriefingEntry(
                    id=row["id"],
                    title=str(row["title"]),
                    status=str(row["status"]),
                    generated_at=row["generated_at"],
                    stale_after=row.get("stale_after"),
                    summary=row.get("summary"),
                )
                for row in rows
            ],
            stale_count=len(stale),
            control_gaps=[
                IntelligenceControlGapEntry(
                    action="regenerate_report",
                    reason=REPORT_REGENERATE_GAP.reason,
                ),
            ],
        )

    async def regenerate_report(
        self,
        body: ReportRegenerateRequest,
        *,
        actor: str,
    ) -> ReportRegenerateResponse:
        briefing_id = await self._repo.regenerate_briefing(title=body.title, actor=actor)
        await self._repo.record_event(
            event_type="report_regenerate",
            actor=actor,
            reason=body.reason,
            payload={"briefing_id": str(briefing_id), "title": body.title},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="report.regenerate",
            entity_type="briefing",
            entity_id=str(briefing_id),
            payload={"reason": body.reason, "title": body.title},
        )
        return ReportRegenerateResponse(
            id=briefing_id,
            title=body.title,
            status="pending",
            mode="queued",
            audited=True,
            reason=body.reason,
        )

    async def export_report(self, report_id: UUID) -> ReportExportResponse:
        row = await self._repo.briefing_row(report_id)
        if row is None:
            msg = f"Report {report_id} not found"
            raise ValueError(msg)
        return ReportExportResponse(
            id=row["id"],
            title=str(row["title"]),
            export_uri=row.get("export_uri") or row.get("blob_uri"),
            status=str(row["status"]),
        )

    async def costs_overview(self, *, days: int = 30) -> CostsOverviewResponse:
        daily = await fetch_daily_costs(self._conn, days)
        month = current_month_key()
        by_agent = await fetch_costs_by_agent(self._conn, month)
        by_vendor = await fetch_costs_by_vendor(self._conn, month)
        state = await self._repo.cost_state()
        return CostsOverviewResponse(
            days=days,
            total_cost_usd=daily.total_cost_usd,
            daily=daily.entries[:7],
            month=month,
            agent_total_usd=by_agent.total_cost_usd,
            vendor_rows=[
                {"vendor": row.vendor, "source": row.source, "cost_usd": row.cost_usd}
                for row in by_vendor
            ],
            kill_switch_active=bool(state.get("kill_switch_active")),
        )

    async def get_budgets(self) -> CostsBudgetsResponse:
        rows = await self._repo.list_budgets()
        state = await self._repo.cost_state()
        return CostsBudgetsResponse(
            budgets=[
                CostsBudgetEntry(
                    id=int(row["id"]),
                    scope=str(row["scope"]),
                    monthly_limit_usd=Decimal(str(row["monthly_limit_usd"])),
                    warn_threshold_pct=Decimal(str(row["warn_threshold_pct"])),
                    updated_at=row["updated_at"],
                    updated_by=row.get("updated_by"),
                )
                for row in rows
            ],
            kill_switch_active=bool(state.get("kill_switch_active")),
            kill_switch_reason=state.get("kill_switch_reason"),
        )

    async def patch_budgets(
        self,
        body: CostsBudgetPatchRequest,
        *,
        actor: str,
    ) -> CostsBudgetEntry:
        row = await self._repo.patch_budget(
            body.scope,
            monthly_limit_usd=body.monthly_limit_usd,
            warn_threshold_pct=body.warn_threshold_pct,
            actor=actor,
        )
        if row is None:
            msg = f"Budget scope {body.scope} not found"
            raise ValueError(msg)
        await write_audit_log(
            self._conn,
            actor=actor,
            action="costs.budget.patch",
            entity_type="cost_budget",
            entity_id=body.scope,
            payload=body.model_dump(mode="json"),
        )
        return CostsBudgetEntry(
            id=int(row["id"]),
            scope=str(row["scope"]),
            monthly_limit_usd=Decimal(str(row["monthly_limit_usd"])),
            warn_threshold_pct=Decimal(str(row["warn_threshold_pct"])),
            updated_at=row["updated_at"],
            updated_by=row.get("updated_by"),
        )

    async def kill_switch(self, body: CostsKillSwitchRequest, *, actor: str) -> CostsKillSwitchResponse:
        state = await self._repo.set_kill_switch(
            active=body.active,
            reason=body.reason,
            actor=actor,
        )
        await self._repo.record_event(
            event_type="cost_kill_switch",
            actor=actor,
            reason=body.reason,
            payload={"active": body.active},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="costs.kill_switch",
            entity_type="cost_control",
            entity_id="global",
            payload={"active": body.active, "reason": body.reason},
        )
        return CostsKillSwitchResponse(
            kill_switch_active=bool(state["kill_switch_active"]),
            kill_switch_reason=state.get("kill_switch_reason"),
            audited=True,
            reason=body.reason,
        )

    async def ensure_agent_not_blocked(self, agent_id: str) -> None:
        state = await self._repo.cost_state()
        if state.get("kill_switch_active"):
            msg = "Cost kill switch is active — agent runs blocked"
            raise ValueError(msg)
        row = await self._repo.agent_row(agent_id)
        if row is None:
            msg = f"Agent {agent_id} not found"
            raise ValueError(msg)
        if not row["active"]:
            msg = f"Agent {agent_id} is disabled"
            raise ValueError(msg)
        if row["paused"]:
            msg = f"Agent {agent_id} is paused"
            raise ValueError(msg)
