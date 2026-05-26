"""Pydantic models for audit NATS events and API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventMessage(BaseModel):
    """Payload published on ``audit.events.*`` subjects."""

    model_config = ConfigDict(extra="forbid")

    actor: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime | None = None


class VerifyResponse(BaseModel):
    """Result of ``GET /audit/verify``."""

    model_config = ConfigDict(extra="forbid")

    status: str
    rows_checked: int
    first_bad_row_id: int | None = None
    detail: str | None = None
