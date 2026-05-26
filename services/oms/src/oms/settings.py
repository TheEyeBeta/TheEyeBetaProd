"""OMS service settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed OMS configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    service_name: str = "oms"
    host: str = Field(default="127.0.0.1", validation_alias="OMS_HOST")
    port: int = Field(default=7080, validation_alias="OMS_PORT")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="REDIS_URL")
    broker_adapter_url: str = Field(
        default="http://127.0.0.1:7090",
        validation_alias="BROKER_ADAPTER_URL",
    )
    reconciliation_interval_seconds: int = Field(
        default=180,
        validation_alias="OMS_RECONCILIATION_INTERVAL_SECONDS",
    )

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN."""
        raw = self.database_url
        if not raw:
            msg = "DATABASE_URL must be set"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")
