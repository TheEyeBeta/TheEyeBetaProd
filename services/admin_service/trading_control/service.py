"""Emergency Trading orchestration."""

from __future__ import annotations

import json
from typing import Any

import structlog
from audit_log import write_audit_log
from settings import Settings
from trading_control.probes import (
    oms_submissions_paused,
    probe_broker,
    probe_compliance,
    probe_edge_api,
    probe_oms,
    probe_risk,
    set_oms_paused,
)
from trading_control.repository import TradingRepository
from trading_control.tokens import hash_token, mint_approval_token
from zinc_schemas.admin_dto import (
    LiveApprovalRequest,
    LiveApprovalTokenResponse,
    TradingApprovalTokenState,
    TradingEventEntry,
    TradingEventListResponse,
    TradingGateHistoryResponse,
    TradingStatusResponse,
)

log = structlog.get_logger()


class TradingControlService:
    """Trading halt/resume and live approval workflow."""

    def __init__(
        self,
        conn: Any,
        settings: Settings,
        *,
        redis: object | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._redis = redis
        self._repo = TradingRepository(conn)

    @staticmethod
    def _event_entry(row: dict[str, Any]) -> TradingEventEntry:
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            payload = {}
        return TradingEventEntry(
            id=int(row["id"]),
            event_type=str(row["event_type"]),
            actor=str(row["actor"]),
            reason=row.get("reason"),
            payload=payload,
            created_at=row["created_at"],
        )

    async def get_status(self) -> TradingStatusResponse:
        state = await self._repo.get_state()
        token_summary = await self._repo.pending_token_summary()
        live_approved = await self._repo.live_approval_on_accounts()
        submissions_paused = await oms_submissions_paused(self._redis)
        emergency_halt = bool(state.get("emergency_halt"))
        live_enabled = bool(state.get("live_trading_enabled")) and live_approved and not emergency_halt

        broker = await probe_broker(
            self._settings,
            live_approved=live_approved,
            emergency_halt=emergency_halt,
        )
        oms = await probe_oms(
            self._redis,
            emergency_halt=emergency_halt,
            submissions_paused=submissions_paused,
        )
        risk = await probe_risk(self._settings)
        compliance = await probe_compliance(self._settings)
        edge_api = await probe_edge_api(self._settings)

        return TradingStatusResponse(
            live_trading_enabled=live_enabled,
            broker_mode=str(state.get("broker_mode") or self._settings.broker_mode),
            emergency_halt=emergency_halt,
            approval_token_state=TradingApprovalTokenState(
                pending_tokens=int(token_summary.get("pending") or 0),
                last_issued_at=token_summary.get("last_issued_at"),
                next_expires_at=token_summary.get("next_expiry"),
            ),
            last_halt_reason=state.get("last_halt_reason"),
            last_halt_at=state.get("last_halt_at"),
            last_resume_reason=state.get("last_resume_reason"),
            last_resume_at=state.get("last_resume_at"),
            last_operator=state.get("last_operator"),
            broker=broker,
            oms=oms,
            risk=risk,
            compliance=compliance,
            edge_api=edge_api,
            checked_at=TradingRepository.utc_now(),
        )

    async def issue_live_approval_token(self, *, actor: str, reason: str) -> LiveApprovalTokenResponse:
        token, token_hash, expires_at = mint_approval_token(
            ttl_minutes=self._settings.trading_approval_token_minutes,
        )
        row = await self._repo.insert_token(
            token_hash=token_hash,
            issued_by=actor,
            expires_at=expires_at,
        )
        await self._repo.record_event(
            event_type="live_approval_token_issued",
            actor=actor,
            reason=reason,
            payload={"token_id": str(row["token_id"]), "expires_at": expires_at.isoformat()},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="trading.live_approval_token",
            entity_type="trading",
            entity_id="live-approval",
            payload={"reason": reason, "expires_at": expires_at.isoformat()},
        )
        return LiveApprovalTokenResponse(
            token=token,
            expires_at=expires_at,
            message="Single-use token — present with live-approval to enable live trading.",
        )

    async def approve_live_trading(
        self,
        body: LiveApprovalRequest,
        *,
        actor: str,
    ) -> TradingStatusResponse:
        if body.confirm is not True:
            msg = "confirm must be true to enable live trading"
            raise ValueError(msg)
        consumed = await self._repo.consume_token(hash_token(body.token), consumed_by=actor)
        if consumed is None:
            msg = "Invalid, expired, or already-used approval token"
            raise ValueError(msg)
        await self._repo.ensure_live_account()
        await self._repo.grant_live_approval_on_accounts()
        await self._repo.save_state(
            live_trading_enabled=True,
            broker_mode="live",
            last_operator=actor,
        )
        await self._repo.record_event(
            event_type="live_approval",
            actor=actor,
            reason=body.reason,
            payload={"token_id": str(consumed["token_id"])},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="trading.live_approval",
            entity_type="trading",
            entity_id="live",
            payload={"reason": body.reason},
        )
        log.warning("live_trading_enabled", actor=actor)
        return await self.get_status()

    async def emergency_halt(self, *, actor: str, reason: str) -> TradingStatusResponse:
        await self._repo.save_state(
            emergency_halt=True,
            live_trading_enabled=False,
            last_halt_reason=reason,
            last_halt_at=TradingRepository.utc_now(),
            last_halt_by=actor,
            last_operator=actor,
        )
        await set_oms_paused(self._redis, paused=True)
        await self._repo.record_event(
            event_type="emergency_halt",
            actor=actor,
            reason=reason,
            payload={"oms_paused": True},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="trading.emergency_halt",
            entity_type="trading",
            entity_id="halt",
            payload={"reason": reason},
        )
        log.warning("emergency_halt_activated", actor=actor, reason=reason)
        return await self.get_status()

    async def resume_from_halt(self, *, actor: str, reason: str) -> TradingStatusResponse:
        state = await self._repo.get_state()
        if not state.get("emergency_halt"):
            msg = "Trading is not in emergency halt"
            raise ValueError(msg)
        await self._repo.save_state(
            emergency_halt=False,
            last_resume_reason=reason,
            last_resume_at=TradingRepository.utc_now(),
            last_resume_by=actor,
            last_operator=actor,
        )
        await set_oms_paused(self._redis, paused=False)
        await self._repo.record_event(
            event_type="resume_from_halt",
            actor=actor,
            reason=reason,
            payload={"live_trading_restored": False},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="trading.resume_from_halt",
            entity_type="trading",
            entity_id="halt",
            payload={"reason": reason, "note": "Live trading not auto-enabled"},
        )
        log.info("emergency_halt_cleared", actor=actor, reason=reason)
        return await self.get_status()

    async def list_events(self, *, limit: int = 100) -> TradingEventListResponse:
        rows = await self._repo.list_events(limit=limit)
        return TradingEventListResponse(
            events=[self._event_entry(row) for row in rows],
        )

    async def gate_history(self, *, limit: int = 100) -> TradingGateHistoryResponse:
        rows = await self._repo.list_gate_history(limit=limit)
        return TradingGateHistoryResponse(
            entries=[self._event_entry(row) for row in rows],
        )
