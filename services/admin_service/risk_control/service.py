"""Risk cockpit orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import structlog
from audit_log import write_audit_log
from risk_control.client import compute_portfolio_metrics
from risk_control.registry import LIMIT_EDIT_GAP, TRADING_LOCK_GAP, RiskControlGap
from risk_control.repository import RiskRepository
from settings import Settings
from zinc_schemas.admin_dto import (
    RiskBreachEntry,
    RiskBreachListResponse,
    RiskComputeResponse,
    RiskControlGapEntry,
    RiskEventEntry,
    RiskFailureEntry,
    RiskFailureListResponse,
    RiskHistoryResponse,
    RiskLimitPatchRequest,
    RiskLimitsResponse,
    RiskMetricsResponse,
    RiskOverrideRequest,
    RiskOverrideResponse,
    RiskStatusResponse,
)

log = structlog.get_logger()


class RiskControlService:
    """Supervise trading decisions via metrics, limits, overrides, and audit."""

    def __init__(self, conn: Any, settings: Settings) -> None:
        self._conn = conn
        self._settings = settings
        self._repo = RiskRepository(conn)

    def _gaps(self) -> list[RiskControlGapEntry]:
        return [
            RiskControlGapEntry(action=LIMIT_EDIT_GAP.action, reason=LIMIT_EDIT_GAP.reason),
            RiskControlGapEntry(action=TRADING_LOCK_GAP.action, reason=TRADING_LOCK_GAP.reason),
        ]

    async def _portfolio_id(self, portfolio_id: str | None) -> str:
        if portfolio_id:
            return portfolio_id
        default = self._settings.risk_default_portfolio_id.strip()
        if default:
            return default
        resolved = await self._repo.default_portfolio_id()
        if resolved is None:
            msg = "No portfolio available for risk cockpit"
            raise ValueError(msg)
        return resolved

    async def _service_health(self) -> tuple[str, bool | None]:
        url = f"{self._settings.risk_http_base_url()}/health"
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

    async def get_status(self, *, portfolio_id: str | None = None) -> RiskStatusResponse:
        pid = await self._portfolio_id(portfolio_id)
        limits_row = await self._repo.get_limits_row()
        state = await self._repo.get_state()
        trading = await self._repo.trading_halt_state()
        metrics = await self._repo.latest_metrics(pid)
        mandate = await self._repo.portfolio_mandate(pid)
        breaches = await self._repo.list_breaches(pid, limits_row["limits"])
        overrides = await self._repo.list_overrides()
        health, reachable = await self._service_health()
        stale = await self._repo.metrics_stale(pid)

        raw = (metrics or {}).get("raw") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        cluster = (raw or {}).get("cluster_exposures") or {}

        return RiskStatusResponse(
            portfolio_id=pid,
            service_health=health,
            service_reachable=reachable,
            metrics_stale=stale,
            last_compute_at=state.get("last_compute_at"),
            last_compute_by=state.get("last_compute_by"),
            limit_version=int(limits_row["version"]),
            limits_source_mandate=mandate,
            limits_overlay=limits_row["limits"],
            portfolio_exposure={
                "gross": float((metrics or {}).get("gross_exposure") or 0),
                "net": float((metrics or {}).get("net_exposure") or 0),
            },
            var_95=float((metrics or {}).get("var_95") or 0) if metrics else None,
            cvar_95=float((metrics or {}).get("cvar_95") or 0) if metrics else None,
            concentration_hhi=float((metrics or {}).get("concentration_hhi") or 0) if metrics else None,
            correlation_clusters={k: float(v) for k, v in cluster.items()},
            active_breach_count=len(breaches),
            active_override_count=len(overrides),
            trading_locked=bool(state.get("trading_locked")),
            emergency_halt=bool(trading.get("emergency_halt")),
            live_trading_enabled=bool(trading.get("live_trading_enabled")),
            control_gaps=self._gaps(),
            checked_at=RiskRepository.utc_now(),
        )

    async def get_metrics(self, *, portfolio_id: str | None = None) -> RiskMetricsResponse:
        pid = await self._portfolio_id(portfolio_id)
        metrics = await self._repo.latest_metrics(pid)
        stale = await self._repo.metrics_stale(pid)
        if metrics is None:
            return RiskMetricsResponse(
                portfolio_id=pid,
                metrics=None,
                stale=True,
                checked_at=RiskRepository.utc_now(),
            )
        raw = metrics.get("raw") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        return RiskMetricsResponse(
            portfolio_id=pid,
            metrics={
                "ts": metrics["ts"].isoformat(),
                "var_95": float(metrics.get("var_95") or 0),
                "cvar_95": float(metrics.get("cvar_95") or 0),
                "max_drawdown": float(metrics.get("max_drawdown") or 0),
                "gross_exposure": float(metrics.get("gross_exposure") or 0),
                "net_exposure": float(metrics.get("net_exposure") or 0),
                "beta_spy": float(metrics.get("beta_spy") or 0),
                "concentration_hhi": float(metrics.get("concentration_hhi") or 0),
                "cluster_exposures": (raw or {}).get("cluster_exposures") or {},
            },
            stale=stale,
            checked_at=RiskRepository.utc_now(),
        )

    async def get_limits(self) -> RiskLimitsResponse:
        row = await self._repo.get_limits_row()
        mandate_portfolio = await self._portfolio_id(None)
        mandate = await self._repo.portfolio_mandate(mandate_portfolio)
        return RiskLimitsResponse(
            version=int(row["version"]),
            limits=row["limits"],
            mandate_limits=mandate,
            editable=True,
            control_gaps=[RiskControlGapEntry(action=LIMIT_EDIT_GAP.action, reason=LIMIT_EDIT_GAP.reason)],
            updated_at=row.get("updated_at"),
            updated_by=row.get("updated_by"),
        )

    async def patch_limits(
        self,
        body: RiskLimitPatchRequest,
        *,
        actor: str,
    ) -> RiskLimitsResponse:
        updated = await self._repo.patch_limits(body.limits, updated_by=actor)
        await self._repo.record_event(
            event_type="limits_patch",
            actor=actor,
            reason=body.reason,
            payload={"version": updated["version"], "keys": sorted(body.limits.keys())},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="risk.limits.patch",
            entity_type="risk",
            entity_id="limits",
            payload={"reason": body.reason, "version": updated["version"]},
        )
        return await self.get_limits()

    async def list_breaches(self, *, portfolio_id: str | None = None) -> RiskBreachListResponse:
        pid = await self._portfolio_id(portfolio_id)
        limits = (await self._repo.get_limits_row())["limits"]
        rows = await self._repo.list_breaches(pid, limits)
        return RiskBreachListResponse(
            portfolio_id=pid,
            breaches=[
                RiskBreachEntry(
                    check=str(row["check"]),
                    limit=float(row["limit"]),
                    actual=float(row["actual"]),
                    severity=str(row["severity"]),
                )
                for row in rows
            ],
        )

    async def list_failures(self) -> RiskFailureListResponse:
        rows = await self._repo.list_failures()
        return RiskFailureListResponse(
            failures=[
                RiskFailureEntry(
                    portfolio_id=str(row["portfolio_id"]),
                    ts=row["ts"],
                    failed_checks=list(row.get("failed_checks") or []),
                    outcome=str(row.get("outcome") or "BLOCK"),
                )
                for row in rows
            ],
        )

    async def history(self, *, limit: int = 100) -> RiskHistoryResponse:
        rows = await self._repo.list_history(limit=limit)
        return RiskHistoryResponse(
            entries=[
                RiskEventEntry(**self._event_entry(row))  # type: ignore[arg-type]
                for row in rows
            ],
        )

    async def list_overrides(self) -> list[dict[str, Any]]:
        return await self._repo.list_overrides()

    async def compute(
        self,
        *,
        actor: str,
        reason: str,
        portfolio_id: str | None = None,
    ) -> RiskComputeResponse:
        pid = await self._portfolio_id(portfolio_id)
        mode = "remote"
        try:
            result = await compute_portfolio_metrics(self._settings, pid)
        except (httpx.HTTPError, OSError, ValueError):
            mode = "local"
            result = {"portfolio_id": pid, "note": "risk-service unreachable; state recorded only"}
        await self._repo.save_state(
            last_compute_at=RiskRepository.utc_now(),
            last_compute_by=actor,
            last_compute_portfolio_id=UUID(pid),
        )
        await self._repo.record_event(
            event_type="compute",
            actor=actor,
            reason=reason,
            payload={"portfolio_id": pid, "mode": mode},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="risk.compute",
            entity_type="risk",
            entity_id=pid,
            payload={"reason": reason, "mode": mode},
        )
        metrics = await self.get_metrics(portfolio_id=pid)
        return RiskComputeResponse(
            portfolio_id=pid,
            mode=mode,
            metrics=metrics.metrics,
            audited=True,
            reason=reason,
        )

    async def override(
        self,
        body: RiskOverrideRequest,
        *,
        actor: str,
    ) -> RiskOverrideResponse:
        expires = None
        if body.expires_in_minutes:
            expires = RiskRepository.utc_now() + timedelta(minutes=body.expires_in_minutes)
        row = await self._repo.insert_override(
            portfolio_id=body.portfolio_id,
            check_name=body.check_name,
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
                "check_name": body.check_name,
                "portfolio_id": body.portfolio_id,
            },
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action="risk.override",
            entity_type="risk",
            entity_id=str(row["id"]),
            payload={
                "reason": body.reason,
                "check_name": body.check_name,
                "portfolio_id": body.portfolio_id,
            },
        )
        return RiskOverrideResponse(
            id=int(row["id"]),
            portfolio_id=str(row["portfolio_id"]) if row.get("portfolio_id") else None,
            check_name=str(row["check_name"]),
            reason=str(row["reason"]),
            expires_at=row.get("expires_at"),
            audited=True,
        )

    async def set_trading_lock(
        self,
        *,
        actor: str,
        reason: str,
        locked: bool,
    ) -> RiskStatusResponse:
        if locked:
            await self._repo.save_state(
                trading_locked=True,
                lock_reason=reason,
                locked_by=actor,
                locked_at=RiskRepository.utc_now(),
            )
            event_type = "trading_lock"
            action = "risk.trading_lock"
        else:
            await self._repo.save_state(
                trading_locked=False,
                lock_reason=None,
                locked_by=None,
                locked_at=None,
            )
            event_type = "trading_unlock"
            action = "risk.trading_unlock"
        await self._repo.record_event(
            event_type=event_type,
            actor=actor,
            reason=reason,
            payload={"advisory_only": True},
        )
        await write_audit_log(
            self._conn,
            actor=actor,
            action=action,
            entity_type="risk",
            entity_id="trading_lock",
            payload={"reason": reason, "locked": locked},
        )
        return await self.get_status()
