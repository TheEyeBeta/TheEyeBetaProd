"""Readiness probes for broker, OMS, risk, compliance, and edge APIs."""

from __future__ import annotations

import httpx
import structlog
from edge.probes import is_port_listening, probe_http_health
from settings import Settings
from trading_control.repository import TradingRepository
from zinc_schemas.admin_dto import TradingComponentStatus

log = structlog.get_logger()


async def _http_reachable(url: str, *, path: str = "/health") -> tuple[bool, str]:
    target = f"{url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(target)
            if response.status_code == 200:
                return True, "reachable"
            return False, f"HTTP {response.status_code}"
    except (httpx.HTTPError, OSError) as exc:
        return False, str(exc)[:200]


async def probe_broker(
    settings: Settings,
    *,
    live_approved: bool,
    emergency_halt: bool,
) -> TradingComponentStatus:
    if emergency_halt:
        return TradingComponentStatus(
            name="broker",
            status="halted",
            message="Emergency halt active",
            reachable=False,
        )
    mode = settings.broker_mode.strip().lower()
    if mode == "live" and not live_approved:
        return TradingComponentStatus(
            name="broker",
            status="blocked",
            message="Live mode requires DB live_approval",
            reachable=None,
        )
    reachable, detail = await _http_reachable(settings.broker_adapter_url)
    status = "ready" if reachable else "unknown"
    return TradingComponentStatus(
        name="broker",
        status=status,
        message=f"mode={mode}; {detail}",
        reachable=reachable,
    )


async def probe_oms(
    redis: object | None,
    *,
    emergency_halt: bool,
    submissions_paused: bool,
) -> TradingComponentStatus:
    if emergency_halt or submissions_paused:
        return TradingComponentStatus(
            name="oms",
            status="halted",
            message="Submissions paused (reconciliation or emergency halt)",
            reachable=None,
        )
    return TradingComponentStatus(
        name="oms",
        status="ready",
        message="Submissions open",
        reachable=True,
    )


async def probe_dependency_service(
    name: str,
    base_url: str,
) -> TradingComponentStatus:
    reachable, detail = await _http_reachable(base_url)
    return TradingComponentStatus(
        name=name,
        status="ready" if reachable else "unknown",
        message=detail,
        reachable=reachable,
    )


async def probe_edge_api(settings: Settings) -> TradingComponentStatus:
    """Cloudflare-facing API reachability for trading dependencies."""
    if settings.trading_uses_local_mode():
        return TradingComponentStatus(
            name="edge_api",
            status="unknown",
            message="Local mode — edge probes skipped",
            reachable=None,
        )
    dataapi_ok = await is_port_listening("127.0.0.1", 7000)
    api_ok = await is_port_listening("127.0.0.1", 8000)
    dataapi_health, _ = await probe_http_health("127.0.0.1", 7000, "/health")
    messages: list[str] = []
    if dataapi_ok:
        messages.append(f"dataapi:7000/{dataapi_health}")
    else:
        messages.append("dataapi:7000 down")
    if api_ok:
        messages.append("api:8000 up")
    else:
        messages.append("api:8000 down")
    reachable = dataapi_ok and dataapi_health == "healthy"
    status = "ready" if reachable else "degraded"
    return TradingComponentStatus(
        name="edge_api",
        status=status,
        message="; ".join(messages),
        reachable=reachable,
    )


async def probe_risk(settings: Settings) -> TradingComponentStatus:
    return await probe_dependency_service("risk", settings.risk_service_url)


async def probe_compliance(settings: Settings) -> TradingComponentStatus:
    return await probe_dependency_service("compliance", settings.compliance_http_base_url())


async def oms_submissions_paused(redis: object | None) -> bool:
    if redis is None:
        return False
    try:
        value = await redis.get(TradingRepository.OMS_PAUSE_KEY)  # type: ignore[attr-defined]
        return value == "1"
    except Exception as exc:  # noqa: BLE001
        log.warning("oms_pause_probe_failed", error=str(exc))
        return False


async def set_oms_paused(redis: object | None, *, paused: bool) -> None:
    if redis is None:
        return
    try:
        if paused:
            await redis.set(TradingRepository.OMS_PAUSE_KEY, "1")  # type: ignore[attr-defined]
        else:
            await redis.delete(TradingRepository.OMS_PAUSE_KEY)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        log.warning("oms_pause_set_failed", error=str(exc))
