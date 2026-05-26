"""R&D agent service settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed rnd-agent configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    service_name: str = "rnd-agent"
    host: str = Field(default="127.0.0.1", validation_alias="RND_AGENT_HOST")
    port: int = Field(default=7120, validation_alias="RND_AGENT_PORT")
    rnd_database_url: str = Field(default="", validation_alias="RND_DATABASE_URL")
    litellm_proxy_url: str = Field(
        default="http://127.0.0.1:7020",
        validation_alias="LITELLM_PROXY_URL",
    )
    litellm_key_rnd_agent: str = Field(default="", validation_alias="LITELLM_KEY_RND_AGENT")
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    guard_grpc_target: str = Field(
        default="127.0.0.1:7040",
        validation_alias="GUARD_SERVICE_GRPC_TARGET",
    )
    repo_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[4])
    run_cron_hour: int = Field(default=9, validation_alias="RND_RUN_CRON_HOUR")
    run_cron_minute: int = Field(default=0, validation_alias="RND_RUN_CRON_MINUTE")
    digest_cron_hour: int = Field(default=10, validation_alias="RND_DIGEST_CRON_HOUR")
    digest_cron_minute: int = Field(default=0, validation_alias="RND_DIGEST_CRON_MINUTE")
    dry_run: bool = Field(default=False, validation_alias="RND_DRY_RUN")
    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="SMTP_PORT")
    smtp_user: str = Field(default="", validation_alias="SMTP_USER")
    smtp_password: str = Field(default="", validation_alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", validation_alias="SMTP_FROM")
    smtp_to: str = Field(default="", validation_alias="SMTP_TO")
    smtp_use_tls: bool = Field(default=True, validation_alias="SMTP_USE_TLS")

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN for ``tb_rnd_readonly``."""
        raw = self.rnd_database_url
        if not raw:
            msg = "RND_DATABASE_URL must be set"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")
