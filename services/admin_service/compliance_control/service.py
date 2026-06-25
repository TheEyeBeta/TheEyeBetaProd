"""Compliance / Legal cockpit orchestration."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import structlog
from audit_log import write_audit_log
from compliance_control.client import check_order
from compliance_control.registry import (
    LEGAL_HOLD_ENFORCEMENT_GAP,
    OVERRIDE_ENFORCEMENT_GAP,
    RESTRICTED_LIST_GAP,
    RULE_CATALOG,
    RULE_EDIT_GAP,
    ComplianceControlGap,
)
from compliance_control.repository import ComplianceRepository
from settings import Settings
from zinc_schemas.admin_dto import (
    ComplianceCheckEntry,
    ComplianceCheckListResponse,
    ComplianceControlGapEntry,
    ComplianceEventEntry,
    ComplianceExceptionCreateRequest,
    ComplianceExceptionEntry,
    ComplianceExceptionListResponse,
    ComplianceHistoryResponse,
    ComplianceLegalHoldRequest,
    ComplianceLegalHoldResponse,
    ComplianceOverrideRequest,
    ComplianceOverrideResponse,
    ComplianceRecheckResponse,
    ComplianceRuleEntry,
    ComplianceRulesPatchRequest,
    ComplianceRulesResponse,
    ComplianceStatusResponse,
)
from zinc_schemas.restricted import load_restricted_list

log = structlog.get_logger()


class ComplianceControlService:
    """Operate compliance rules, checks, exceptions, legal holds, and audit."""

    def __init__(self, conn: Any, settings: Settings) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = ComplianceRepository(conn)

    def _gaps(self) -> list[ComplianceControlGapEntry]:
        gaps: list[ComplianceControlGap] = [
            RULE_EDIT_GAP,
            RESTRICTED_LIST_GAP,
            LEGAL_HOLD_ENFORCEMENT_GAP,
            OVERRIDE_ENFORCEMENT_GAP,
        ]
        return [ComplianceControlGapEntry(action=g.action, reason=g.reason) for g in gaps]

    async def _portfolio_id(self, portfolio_id: str | None) -> str:
        if portfolio_id:
            return portfolio_id
        default = self._settings.compliance_default_portfolio_id.strip()
        if default:
            return default
        resolved = await self._repo.default_portfolio_id()
        if resolved is None:
            msg = "No portfolio available for compliance cockpit"
            raise ValueError(msg)
        return resolved

    async def _instrument_id(self, instrument_id: int | None) -> int:
        if instrument_id is not None:
            return instrument_id
        default = self._settings.compliance_recheck_instrument_id
        if default > 0:
            return default
        resolved = await self._repo.default_instrument_id()
        if resolved is None:
            msg = "No instrument available for compliance recheck"
            raise ValueError(msg)
        return resolved

    async def _service_health(self) -> tuple[str, bool | None]:
        url = f"{self._settings.compliance_http_base_url()}/health"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url)
                ok = response.status_code == 200
                return ("ready" if ok else "degraded", ok)
        except (httpx.HTTPError, OSError):
            return ("unknown", False)

    @staticmethod
    def _event_entry(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        return {
            "id": int(row["id"]),
            "event_type": str(row["event_type"]),
            "actor": str(row["actor"]),
            "reason": row.get("reason"),
            "payload": payload if isinstance(payload, dict) else {},
            "created_at": row["created_at"],
        }

    @staticmethod
    def _check_entry(row: dict[str, Any]) -> ComplianceCheckEntry:
        return ComplianceCheckEntry(
            id=str(row["id"]),
            order_id=str(row["order_id"]) if row.get("order_id") else None,
            portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
            rule_id=str(row["rule_id"]),
            outcome=str(row["outcome"]),
            detail=row.get("detail"),
            checked_at=row["checked_at"],
        )

    async def get_status(self, *, portfolio_id: str | None = None) -> ComplianceStatusResponse:
        pid = await self._portfolio_id(portfolio_id)
        rules_row = await self._repo.get_rules_row()
        state = await self._repo.get_state()
        mandate = await self._repo.portfolio_mandate_rules(pid)
        failed = await self._repo.list_failed_checks(limit=100, portfolio_id=pid)
        overrides = await self._repo.list_overrides()
        exceptions = await self._repo.list_exceptions()
        holds = await self._repo.list_legal_holds()
        health, reachable = await self._service_health()
        restricted = load_restricted_list()
        entries = restricted.all_entries()
        unresolved_guard = await self._repo.unresolved_guard_violations()

        return ComplianceStatusResponse(
            portfolio_id=pid,
            service_health=health,
            service_reachable=reachable,
            rule_version=int(rules_row["version"]),
            rules_overlay=rules_row["rules"],
            mandate_rules=mandate,
            rule_catalog=[ComplianceRuleEntry(**item) for item in RULE_CATALOG],
            restricted_list={
                "source": "zinc_schemas/restricted.yaml",
                "entry_count": len(entries),
                "blacklist_count": sum(1 for e in entries if e.list_type == "blacklist"),
            },
            recent_failed_count=len(failed),
            active_override_count=len(overrides),
            active_exception_count=len(exceptions),
            active_legal_hold_count=len(holds),
            unresolved_guard_violations=unresolved_guard,
            last_recheck_at=state.get("last_recheck_at"),
            last_recheck_by=state.get("last_recheck_by"),
            control_gaps=self._gaps(),
            checked_at=ComplianceRepository.utc_now(),
        )

    async def list_checks(
        self,
        *,
        portfolio_id: str | None = None,
        limit: int = 50,
    ) -> ComplianceCheckListResponse:
        pid = await self._portfolio_id(portfolio_id) if portfolio_id else None
        rows = await self._repo.list_checks(limit=limit, portfolio_id=pid)
        return ComplianceCheckListResponse(
            portfolio_id=pid,
            checks=[self._check_entry(row) for row in rows],
        )

    async def list_failed_checks(
        self,
        *,
        portfolio_id: str | None = None,
        limit: int = 50,
    ) -> list[ComplianceCheckEntry]:
        pid = await self._portfolio_id(portfolio_id) if portfolio_id else None
        rows = await self._repo.list_failed_checks(limit=limit, portfolio_id=pid)
        return [self._check_entry(row) for row in rows]

    async def recheck(
        self,
        *,
        actor: str,
        reason: str,
        portfolio_id: str | None = None,
        instrument_id: int | None = None,
        side: str = "buy",
        qty: float = 1.0,
        limit_price: float = 100.0,
    ) -> ComplianceRecheckResponse:
        pid = await self._portfolio_id(portfolio_id)
        iid = await self._instrument_id(instrument_id)
        mode = "remote"
        result: dict[str, object]
        try:
            result = await check_order(
                self._settings,
                portfolio_id=pid,
                instrument_id=iid,
                side=side,
                qty=qty,
                limit_price=limit_price,
            )
        except (httpx.HTTPError, OSError):
            mode = "local"
            result = {
                "approved": None,
                "outcome": "UNKNOWN",
                "reason": "compliance-service unreachable; state recorded only",
            }
        await self._repo.save_state(
            last_recheck_at=ComplianceRepository.utc_now(),
            last_recheck_by=actor,
            last_recheck_portfolio_id=UUID(pid),
        )
        await self._repo.record_event(
            event_type="recheck",
            actor=actor,
            reason=reason,
            payload={"portfolio_id": pid, "instrument_id": iid, "mode": mode},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="compliance.recheck",
            entity_type="compliance",
            entity_id=pid,
            payload={"reason": reason, "mode": mode, "instrument_id": iid},
        )
        checks = await self.list_checks(portfolio_id=pid, limit=10)
        return ComplianceRecheckResponse(
            portfolio_id=pid,
            instrument_id=iid,
            mode=mode,
            outcome=str(result.get("outcome") or "UNKNOWN"),
            approved=result.get("approved") if isinstance(result.get("approved"), bool) else None,
            failed_checks=list(result.get("failed_checks") or []),
            recent_checks=checks.checks,
            audited=True,
            reason=reason,
        )

    async def get_rules(self) -> ComplianceRulesResponse:
        row = await self._repo.get_rules_row()
        mandate_portfolio = await self._portfolio_id(None)
        mandate = await self._repo.portfolio_mandate_rules(mandate_portfolio)
        return ComplianceRulesResponse(
            version=int(row["version"]),
            rules=row["rules"],
            mandate_rules=mandate,
            editable=True,
            control_gaps=[ComplianceControlGapEntry(action=RULE_EDIT_GAP.action, reason=RULE_EDIT_GAP.reason)],
            updated_at=row.get("updated_at"),
            updated_by=row.get("updated_by"),
        )

    async def patch_rules(
        self,
        body: ComplianceRulesPatchRequest,
        *,
        actor: str,
    ) -> ComplianceRulesResponse:
        updated = await self._repo.patch_rules(body.rules, updated_by=actor)
        await self._repo.record_event(
            event_type="rules_patch",
            actor=actor,
            reason=body.reason,
            payload={"version": updated["version"], "keys": sorted(body.rules.keys())},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="compliance.rules.patch",
            entity_type="compliance",
            entity_id="rules",
            payload={"reason": body.reason, "version": updated["version"]},
        )
        return await self.get_rules()

    async def override(
        self,
        body: ComplianceOverrideRequest,
        *,
        actor: str,
    ) -> ComplianceOverrideResponse:
        expires = None
        if body.expires_in_minutes:
            expires = ComplianceRepository.utc_now() + timedelta(minutes=body.expires_in_minutes)
        row = await self._repo.insert_override(
            portfolio_id=body.portfolio_id,
            rule_id=body.rule_id,
            reason=body.reason,
            actor=actor,
            expires_at=expires,
        )
        await self._repo.record_event(
            event_type="override",
            actor=actor,
            reason=body.reason,
            payload={
                "override_id": row["id"],
                "rule_id": body.rule_id,
                "portfolio_id": body.portfolio_id,
            },
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="compliance.override",
            entity_type="compliance",
            entity_id=str(row["id"]),
            payload={
                "reason": body.reason,
                "rule_id": body.rule_id,
                "portfolio_id": body.portfolio_id,
            },
        )
        return ComplianceOverrideResponse(
            id=int(row["id"]),
            portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
            rule_id=str(row["rule_id"]),
            reason=str(row["reason"]),
            expires_at=row.get("expires_at"),
            audited=True,
        )

    async def list_exceptions(self) -> ComplianceExceptionListResponse:
        rows = await self._repo.list_exceptions()
        return ComplianceExceptionListResponse(
            exceptions=[
                ComplianceExceptionEntry(
                    id=int(row["id"]),
                    portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
                    rule_id=str(row["rule_id"]),
                    reason=str(row["reason"]),
                    actor=str(row["actor"]),
                    expires_at=row.get("expires_at"),
                    created_at=row["created_at"],
                )
                for row in rows
            ],
        )

    async def create_exception(
        self,
        body: ComplianceExceptionCreateRequest,
        *,
        actor: str,
    ) -> ComplianceExceptionEntry:
        expires = None
        if body.expires_in_minutes:
            expires = ComplianceRepository.utc_now() + timedelta(minutes=body.expires_in_minutes)
        row = await self._repo.insert_exception(
            portfolio_id=body.portfolio_id,
            rule_id=body.rule_id,
            reason=body.reason,
            actor=actor,
            expires_at=expires,
        )
        await self._repo.record_event(
            event_type="exception_create",
            actor=actor,
            reason=body.reason,
            payload={
                "exception_id": row["id"],
                "rule_id": body.rule_id,
                "portfolio_id": body.portfolio_id,
            },
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="compliance.exception.create",
            entity_type="compliance",
            entity_id=str(row["id"]),
            payload={
                "reason": body.reason,
                "rule_id": body.rule_id,
                "portfolio_id": body.portfolio_id,
            },
        )
        return ComplianceExceptionEntry(
            id=int(row["id"]),
            portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
            rule_id=str(row["rule_id"]),
            reason=str(row["reason"]),
            actor=str(row["actor"]),
            expires_at=row.get("expires_at"),
            created_at=row["created_at"],
        )

    async def legal_hold(
        self,
        body: ComplianceLegalHoldRequest,
        *,
        actor: str,
    ) -> ComplianceLegalHoldResponse:
        if body.action == "apply":
            row = await self._repo.apply_legal_hold(
                entity_type=body.entity_type,
                entity_id=body.entity_id,
                reason=body.reason,
                actor=actor,
            )
            event_type = "legal_hold_apply"
            action = "compliance.legal_hold.apply"
        else:
            row = await self._repo.release_legal_hold(
                entity_type=body.entity_type,
                entity_id=body.entity_id,
                actor=actor,
            )
            if row is None:
                msg = f"No active legal hold for {body.entity_type}:{body.entity_id}"
                raise ValueError(msg)
            event_type = "legal_hold_release"
            action = "compliance.legal_hold.release"
        await self._repo.record_event(
            event_type=event_type,
            actor=actor,
            reason=body.reason,
            payload={
                "entity_type": body.entity_type,
                "entity_id": body.entity_id,
                "hold_id": row["id"],
            },
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action=action,
            entity_type="legal_hold",
            entity_id=str(row["id"]),
            payload={
                "reason": body.reason,
                "entity_type": body.entity_type,
                "entity_id": body.entity_id,
                "action": body.action,
            },
        )
        return ComplianceLegalHoldResponse(
            id=int(row["id"]),
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            active=bool(row["active"]),
            reason=str(row["reason"]),
            placed_by=str(row["placed_by"]),
            placed_at=row["placed_at"],
            released_by=row.get("released_by"),
            released_at=row.get("released_at"),
            audited=True,
        )

    async def list_legal_holds(self) -> list[dict[str, Any]]:
        return await self._repo.list_legal_holds()

    async def list_overrides(self) -> list[dict[str, Any]]:
        return await self._repo.list_overrides()

    async def history(self, *, limit: int = 100) -> ComplianceHistoryResponse:
        rows = await self._repo.list_history(limit=limit)
        return ComplianceHistoryResponse(
            entries=[
                ComplianceEventEntry(**self._event_entry(row))  # type: ignore[arg-type]
                for row in rows
            ],
        )
