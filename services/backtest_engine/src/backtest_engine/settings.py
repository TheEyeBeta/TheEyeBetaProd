"""Backtest engine settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    service_name: str = "backtest-engine"
    host: str = Field(default="127.0.0.1", validation_alias="BACKTEST_ENGINE_HOST")
    port: int = Field(default=7100, validation_alias="BACKTEST_ENGINE_PORT")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    minio_endpoint: str = Field(default="127.0.0.1:9000", validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", validation_alias="MINIO_ROOT_USER")
    minio_secret_key: str = Field(default="", validation_alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(
        default="theeyebeta-backtests",
        validation_alias="MINIO_BACKTEST_BUCKET",
    )
    git_sha: str = Field(default="unknown", validation_alias="GIT_COMMIT")

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN."""
        raw = self.database_url
        if not raw:
            msg = "DATABASE_URL must be set"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")
