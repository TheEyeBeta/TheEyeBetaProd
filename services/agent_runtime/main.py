"""FastAPI entrypoint for agent-runtime (port 8004)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Literal
from uuid import UUID

import structlog
from agent_runtime.runner import AgentRunner
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

log = structlog.get_logger()


class Settings(BaseSettings):
    """Service configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "agent-runtime"
    version: str = "0.1.0"
    host: str = Field(default="127.0.0.1", validation_alias="AGENT_RUNTIME_HOST")
    port: int = Field(default=8004, validation_alias="AGENT_RUNTIME_PORT")


class AgentMessage(BaseModel):
    """Peer agent rationale injected for debate rebuttals."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    instrument_symbol: str
    decision: str
    rationale: str


class AgentRunRequest(BaseModel):
    """Body for POST /agents/{agent_id}/run."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    kind: Literal["run", "rebuttal"] = "run"
    agent_messages: list[AgentMessage] = Field(default_factory=list)


class AgentDecisionRow(BaseModel):
    """One instrument decision returned to orchestrators."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str | None = None
    instrument_symbol: str
    instrument_id: int | None = None
    decision: str
    confidence: float
    horizon_days: int
    rationale: str
    key_drivers: list[str] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    """Response from a successful agent run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    snapshot_id: str
    decisions: list[str]
    decision_rows: list[AgentDecisionRow] = Field(default_factory=list)
    cost_usd: float
    market_stance: str
    regime_call: str
    kind: str = "run"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings."""
    return Settings()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info("agent_runtime_started")
    yield
    log.info("agent_runtime_stopped")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="agent-runtime",
        version=settings.version,
        lifespan=_lifespan,
    )

    @app.get("/metrics")
    async def metrics() -> object:
        """Prometheus scrape endpoint."""
        from fastapi import Response

        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": settings.version,
        }

    @app.post("/agents/{agent_id}/run", response_model=AgentRunResponse)
    async def run_agent_endpoint(
        agent_id: str,
        body: AgentRunRequest,
    ) -> AgentRunResponse:
        """Execute one agent run for a packaged snapshot."""
        runner = AgentRunner()
        try:
            summary = await runner.run(
                agent_id,
                body.snapshot_id,
                kind=body.kind,
                agent_messages=[m.model_dump() for m in body.agent_messages],
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.error("agent_run_failed", agent_id=agent_id, error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        rows = [AgentDecisionRow.model_validate(row) for row in summary.get("decision_rows", [])]
        return AgentRunResponse(
            run_id=summary["run_id"],
            snapshot_id=summary["snapshot_id"],
            decisions=summary["decisions"],
            decision_rows=rows,
            cost_usd=float(summary["cost_usd"]),
            market_stance=summary["market_stance"],
            regime_call=summary["regime_call"],
            kind=body.kind,
        )

    return app


app = create_app()


def main() -> None:
    """Run uvicorn when executed as a module."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        factory=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
