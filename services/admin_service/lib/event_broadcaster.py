"""Real-time event broadcaster for WebSocket clients."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger()


class EventBroadcaster:
    """In-process pub/sub for normalized admin events."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue."""
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(
        self,
        *,
        event_type: str,
        severity: str = "info",
        source: str = "system",
        actor: str = "system",
        correlation_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Broadcast one normalized event envelope to all subscribers."""
        envelope: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "ts": datetime.now(tz=UTC).isoformat(),
            "severity": severity,
            "source": source,
            "actor": actor,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "payload": payload or {},
        }
        async with self._lock:
            dead: list[asyncio.Queue[dict[str, Any]]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)
        return envelope

    @staticmethod
    def normalize_nats_message(subject: str, data: bytes) -> dict[str, Any] | None:
        """Map a NATS message to a normalized event envelope payload."""
        try:
            payload = json.loads(data.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": data.decode(errors="replace")[:2000]}

        if subject.startswith("orders.proposed."):
            return {
                "event_type": "order.proposed",
                "severity": "info",
                "source": "master_orchestrator",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject.startswith("orders.approved."):
            return {
                "event_type": "order.approved",
                "severity": "info",
                "source": "admin_service",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject.startswith("broker.fills."):
            return {
                "event_type": "broker.fill",
                "severity": "info",
                "source": "broker_adapter",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject.startswith("audit.events."):
            return {
                "event_type": "audit.event",
                "severity": "info",
                "source": "audit_service",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject.startswith("agents.violations.escalated."):
            return {
                "event_type": "alert.created",
                "severity": "warn",
                "source": "guard_service",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject == "risk.breaches.reconciliation":
            return {
                "event_type": "alert.created",
                "severity": "critical",
                "source": "oms",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        if subject.startswith("trading.emergency."):
            return {
                "event_type": "trading.halt",
                "severity": "critical",
                "source": "admin_service",
                "payload": payload if isinstance(payload, dict) else {"value": payload},
            }
        return None
