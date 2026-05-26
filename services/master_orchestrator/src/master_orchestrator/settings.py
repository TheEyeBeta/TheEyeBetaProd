"""Service configuration."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Master orchestrator settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    service_name: str = "master-orchestrator"
    version: str = "0.1.0"
    host: str = Field(default="127.0.0.1", validation_alias="MASTER_ORCHESTRATOR_HOST")
    port: int = Field(default=7050, validation_alias="MASTER_ORCHESTRATOR_PORT")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    agent_runtime_url: str = Field(
        default="http://127.0.0.1:8004",
        validation_alias="AGENT_RUNTIME_URL",
    )
    risk_service_url: str = Field(default="", validation_alias="RISK_SERVICE_URL")
    risk_metrics_interval_seconds: int = Field(
        default=300,
        validation_alias="RISK_METRICS_INTERVAL_SECONDS",
    )
    risk_metrics_portfolio_ids: str = Field(
        default="",
        validation_alias="RISK_METRICS_PORTFOLIO_IDS",
        description="Comma-separated portfolio UUIDs for scheduled metric recompute",
    )
    compliance_service_url: str = Field(default="", validation_alias="COMPLIANCE_SERVICE_URL")
    default_portfolio_id: str = Field(default="", validation_alias="DEFAULT_PORTFOLIO_ID")
    llm_proxy_url: str = Field(
        default="http://llm-gateway:4000", validation_alias="LITELLM_PROXY_URL"
    )
    llm_virtual_key: str = Field(
        default="",
        validation_alias="LITELLM_KEY_MASTER_ORCHESTRATOR",
    )
    default_order_qty: float = Field(default=100.0, validation_alias="MO_DEFAULT_ORDER_QTY")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="REDIS_URL")

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN."""
        raw = self.database_url
        if not raw:
            msg = "DATABASE_URL must be set"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")
