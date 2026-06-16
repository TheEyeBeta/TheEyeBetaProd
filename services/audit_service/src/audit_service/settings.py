"""Audit service settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed audit service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    service_name: str = "audit-service"
    host: str = Field(default="127.0.0.1", validation_alias="AUDIT_SERVICE_HOST")
    port: int = Field(default=7110, validation_alias="AUDIT_SERVICE_PORT")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    minio_endpoint: str = Field(default="127.0.0.1:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ROOT_USER")
    minio_secret_key: str = Field(default="", validation_alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(
        default="theeyebeta-audit",
        validation_alias="MINIO_AUDIT_BUCKET",
    )
    audit_signing_key: str = Field(default="", validation_alias="AUDIT_SIGNING_KEY")
    export_cron_hour: int = Field(default=3, validation_alias="AUDIT_EXPORT_CRON_HOUR")
    export_cron_minute: int = Field(default=0, validation_alias="AUDIT_EXPORT_CRON_MINUTE")
    jetstream_stream: str = Field(default="AUDIT_EVENTS", validation_alias="AUDIT_JS_STREAM")
    jetstream_durable: str = Field(
        default="audit-service-writer",
        validation_alias="AUDIT_JS_DURABLE",
    )

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN."""
        raw = self.database_url
        if not raw:
            msg = "DATABASE_URL must be set"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")
