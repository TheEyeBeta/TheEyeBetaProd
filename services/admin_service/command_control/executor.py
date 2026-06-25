"""Execute allowlisted commands via existing control-plane services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from audit_log import write_audit_log
from command_control.parser import ParsedCommand
from settings import Settings

log = structlog.get_logger()


@dataclass(slots=True)
class CommandExecutionContext:
    """Runtime dependencies for one command execution."""

    conn: Any
    settings: Settings
    redis: Any | None
    nats: Any | None
    actor: str
    reason: str


class CommandExecutor:
    """Dispatch parsed commands to safe backend APIs (in-process)."""

    async def execute(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        command_id = parsed.definition.id
        dispatch = {
            "worker.run": self._worker_run,
            "worker.stop": self._worker_stop,
            "timer.disable": self._timer_disable,
            "service.restart": self._service_restart,
            "edge.routes.check": self._edge_routes_check,
            "cloudflare.status": self._cloudflare_status,
            "dataapi.health": self._dataapi_health,
            "trading.halt": self._trading_halt,
            "audit.verify": self._audit_verify,
            "risk.compute": self._risk_compute,
            "broker.test": self._broker_test,
            "backtest.run": self._backtest_run,
            "agent.run": self._agent_run,
        }
        handler = dispatch.get(command_id)
        if handler is None:
            msg = f"No executor for {command_id}"
            raise ValueError(msg)
        result = await handler(parsed, ctx)
        await write_audit_log(
            ctx.conn,
            actor=ctx.actor,
            action=f"command.{command_id}",
            entity_type="command",
            entity_id=command_id,
            payload={"command": parsed.raw, "reason": ctx.reason, "result": result},
        )
        return result

    async def _worker_run(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from workers_control.service import WorkersControlService

        worker = parsed.params["worker"]
        svc = WorkersControlService(ctx.conn, ctx.settings)
        response = await svc.force_run(worker, actor=ctx.actor, reason=ctx.reason)
        if response is None:
            msg = f"Worker {worker} not found"
            raise ValueError(msg)
        payload = response.model_dump(mode="json")
        if parsed.params.get("date"):
            payload["advisory_date"] = parsed.params["date"]
        return payload

    async def _worker_stop(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from workers_control.service import WorkersControlService

        worker = parsed.params["worker"]
        svc = WorkersControlService(ctx.conn, ctx.settings)
        response = await svc.stop_worker(worker, actor=ctx.actor, reason=ctx.reason)
        if response is None:
            msg = f"Worker {worker} not found"
            raise ValueError(msg)
        return response.model_dump(mode="json")

    async def _timer_disable(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from workers_control.service import WorkersControlService

        timer = parsed.params["timer"]
        svc = WorkersControlService(ctx.conn, ctx.settings)
        response = await svc.disable_timer(timer, actor=ctx.actor, reason=ctx.reason)
        if response is None:
            msg = f"Timer {timer} not found"
            raise ValueError(msg)
        return response.model_dump(mode="json")

    async def _service_restart(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from services_control.service import ServicesControlService

        name = parsed.params["service"]
        svc = ServicesControlService(ctx.conn, ctx.settings)
        response = await svc.restart(name, actor=ctx.actor, reason=ctx.reason)
        if response is None:
            msg = f"Service {name} not found"
            raise ValueError(msg)
        return response.model_dump(mode="json")

    async def _edge_routes_check(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from edge.service import EdgeRegistryService

        svc = EdgeRegistryService(ctx.settings)
        result = await svc.run_routes_check()
        await write_audit_log(
            ctx.conn,
            actor=ctx.actor,
            action="edge.routes.check",
            entity_type="edge",
            entity_id="registry",
            payload={"ok": result.ok, "command": parsed.raw},
        )
        return result.model_dump(mode="json")

    async def _cloudflare_status(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from edge.service import EdgeRegistryService

        payload = await EdgeRegistryService(ctx.settings).cloudflare_status()
        return payload.model_dump(mode="json")

    async def _dataapi_health(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from market_control.service import MarketControlService

        status = await MarketControlService(ctx.conn, ctx.settings).get_status()
        return {
            "data_api_health": status.data_api_health,
            "public_routes": [row.model_dump(mode="json") for row in status.data_api_public_routes],
        }

    async def _trading_halt(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from trading_control.service import TradingControlService

        svc = TradingControlService(ctx.conn, ctx.settings, redis=ctx.redis)
        status = await svc.emergency_halt(actor=ctx.actor, reason=ctx.reason)
        return status.model_dump(mode="json")

    async def _audit_verify(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from api.audit import call_audit_service_verify

        hours = int(parsed.params.get("hours", "24"))
        to_ts = datetime.now(tz=UTC)
        from_ts = to_ts - timedelta(hours=hours)
        verify = await call_audit_service_verify(ctx.settings, from_ts=from_ts, to_ts=to_ts)
        return verify.model_dump(mode="json")

    async def _risk_compute(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from risk_control.service import RiskControlService

        portfolio = parsed.params.get("portfolio_id") or ctx.settings.risk_default_portfolio_id
        svc = RiskControlService(ctx.conn, ctx.settings)
        response = await svc.compute(
            actor=ctx.actor,
            reason=ctx.reason,
            portfolio_id=portfolio,
        )
        return response.model_dump(mode="json")

    async def _broker_test(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from blotter_control.service import BlotterService

        svc = BlotterService(ctx.conn, ctx.settings, redis=ctx.redis)
        response = await svc.test_connection(actor=ctx.actor, reason=ctx.reason)
        return response.model_dump(mode="json")

    async def _backtest_run(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        import httpx
        from api.backtest import _engine_url, _raise_for_engine_status
        from command_control.parser import default_backtest_dates

        start, end = default_backtest_dates()
        body = {
            "strategy_id": parsed.params["strategy"],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "universe": parsed.params.get("universe", "sp500"),
        }
        url = _engine_url(ctx.settings, "/backtest/run")
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            msg = "backtest-engine unreachable"
            raise ValueError(msg) from exc
        _raise_for_engine_status(response)
        data = response.json()
        await write_audit_log(
            ctx.conn,
            actor=ctx.actor,
            action="start.backtest",
            entity_type="backtest_run",
            entity_id=str(data.get("backtest_run_id") or ""),
            payload={**body, "reason": ctx.reason, "via": "command.console"},
        )
        return data

    async def _agent_run(self, parsed: ParsedCommand, ctx: CommandExecutionContext) -> dict[str, Any]:
        from api.agents import trigger_agent_run_impl
        from command_control.repository import CommandRepository
        from zinc_schemas.admin_dto import RunAgentRequest

        agent_id = parsed.params["agent_id"]
        repo = CommandRepository(ctx.conn)
        snapshot_raw = await repo.latest_snapshot_id()
        if snapshot_raw is None:
            msg = "No packaged snapshot available for agent run"
            raise ValueError(msg)
        body = RunAgentRequest(snapshot_id=UUID(snapshot_raw), kind="run")
        response = await trigger_agent_run_impl(
            ctx.conn,
            ctx.settings,
            agent_id,
            body=body,
            actor=ctx.actor,
        )
        payload = response.model_dump(mode="json")
        if parsed.params.get("alias") != agent_id:
            payload["alias"] = parsed.params.get("alias")
        return payload


def build_preview(parsed: ParsedCommand, *, allowed: bool, denial: str | None = None) -> dict[str, Any]:
    """Build preview payload from a parsed command."""
    definition = parsed.definition
    consequence = definition.preview_output
    if parsed.params:
        consequence = f"{consequence} Params: {parsed.params}"
    return {
        "command_id": definition.id,
        "command_text": parsed.raw,
        "description": definition.description,
        "role_required": definition.role_required,
        "backend_route": definition.backend_route,
        "dangerous": definition.dangerous,
        "confirmation_required": definition.confirmation_required,
        "reason_required": definition.reason_required,
        "audit_category": definition.audit_category,
        "preview_output": definition.preview_output,
        "rollback_note": definition.rollback_note,
        "consequence_preview": consequence,
        "params": parsed.params,
        "allowed": allowed,
        "denial_reason": denial,
    }
