"""WebSocket event stream for admin control plane."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from auth import decode_access_token
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from lib.event_broadcaster import EventBroadcaster

if TYPE_CHECKING:
    from fastapi import FastAPI

log = structlog.get_logger()

router = APIRouter(prefix="/events", tags=["events"])

_NATS_SUBJECTS = [
    "orders.proposed.>",
    "orders.approved.>",
    "broker.fills.>",
    "audit.events.>",
    "agents.violations.escalated.>",
    "risk.breaches.reconciliation",
    "trading.emergency.>",
]


async def start_nats_event_bridge(app: FastAPI) -> None:
    """Subscribe to NATS subjects and forward normalized events to the broadcaster."""
    nc = getattr(app.state, "nats", None)
    broadcaster: EventBroadcaster | None = getattr(app.state, "event_broadcaster", None)
    if nc is None or broadcaster is None:
        return

    async def _handler(msg: Any) -> None:  # noqa: ANN401
        normalized = EventBroadcaster.normalize_nats_message(msg.subject, msg.data)
        if normalized is None:
            return
        await broadcaster.publish(
            event_type=normalized["event_type"],
            severity=normalized["severity"],
            source=normalized["source"],
            payload=normalized["payload"],
        )

    subs = []
    for subject in _NATS_SUBJECTS:
        sub = await nc.subscribe(subject, cb=_handler)
        subs.append(sub)

    async def _drain() -> None:
        for sub in subs:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()

    app.state._nats_event_subs = subs
    app.state._nats_event_drain = _drain
    log.info("admin_nats_event_bridge_started", subjects=len(_NATS_SUBJECTS))


def register_events_routes() -> APIRouter:
    """Attach WebSocket event stream."""

    @router.websocket("/stream")
    async def events_stream(websocket: WebSocket) -> None:
        """Stream normalized admin events.

        Auth protocol (token never in URL):
        1. Client connects (no token in URL).
        2. Server accepts and waits up to 10 s for the first message.
        3. Client sends ``{"type": "auth", "token": "<access_jwt>"}``.
        4. Server validates the JWT; closes with 1008 on any failure.
        5. On success the event stream starts.
        """
        broadcaster: EventBroadcaster | None = getattr(
            websocket.app.state,
            "event_broadcaster",
            None,
        )
        if broadcaster is None:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        await websocket.accept()

        # Phase 1 — authenticate via first message
        settings = websocket.app.state.settings
        actor = "unknown"
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
            if not isinstance(raw, dict) or raw.get("type") != "auth":
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            token = str(raw.get("token", ""))
            token_payload = decode_access_token(token, settings)
            actor = str(token_payload.get("sub", "unknown"))
        except Exception:  # noqa: BLE001 — any failure (timeout, bad token) closes the socket
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Phase 2 — stream events
        queue = await broadcaster.subscribe()
        log.info("admin_ws_connected", sub=actor)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except TimeoutError:
                    await websocket.send_json({"type": "ping", "ts": _event_ping_ts()})
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            log.info("admin_ws_disconnected", sub=actor)
        finally:
            await broadcaster.unsubscribe(queue)

    return router


def _event_ping_ts() -> str:
    """Return ISO timestamp for WS keepalive pings."""
    return datetime.now(tz=UTC).isoformat()
