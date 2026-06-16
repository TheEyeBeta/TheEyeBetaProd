"""Broker-adapter settings."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BrokerMode = Literal["paper", "live"]


class Settings(BaseSettings):
    """Alpaca broker adapter configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    service_name: str = "broker-adapter-alpaca"
    host: str = Field(default="127.0.0.1", validation_alias="BROKER_ADAPTER_HOST")
    port: int = Field(default=7090, validation_alias="BROKER_ADAPTER_PORT")
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="REDIS_OPS_URL")
    mode: BrokerMode = Field(default="paper", validation_alias="BROKER_MODE")

    def pg_dsn(self) -> str:
        """Return a psycopg-compatible DSN."""
        raw = self.database_url
        if not raw:
            msg = "DATABASE_URL must be set for live-mode gate checks"
            raise OSError(msg)
        return raw.replace("+asyncpg", "").replace("+psycopg", "")

    def api_key(self) -> str:
        """Resolve Alpaca API key for the configured mode (primary / zinc account)."""
        if self.mode == "live":
            return (
                os.environ.get("ALPACA_API_KEY_LIVE", "").strip()
                or os.environ.get("ALPACA_API_KEY", "").strip()
            )
        return (
            os.environ.get("ALPACA_API_KEY_PAPER_ZINC", "").strip()
            or os.environ.get("ALPACA_API_KEY_PAPER", "").strip()
            or os.environ.get("ALPACA_API_KEY", "").strip()
            or os.environ.get("APCA_API_KEY_ID", "").strip()
        )

    def api_secret(self) -> str:
        """Resolve Alpaca API secret for the configured mode (primary / zinc account)."""
        if self.mode == "live":
            return (
                os.environ.get("ALPACA_API_SECRET_LIVE", "").strip()
                or os.environ.get("ALPACA_SECRET_KEY", "").strip()
                or os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
            )
        return (
            os.environ.get("ALPACA_API_SECRET_PAPER_ZINC", "").strip()
            or os.environ.get("ALPACA_API_SECRET_PAPER", "").strip()
            or os.environ.get("ALPACA_SECRET_KEY", "").strip()
            or os.environ.get("ALPACA_API_SECRET_KEY", "").strip()
            or os.environ.get("APCA_API_SECRET_KEY", "").strip()
        )

    def api_key_for_account(self, account: str) -> str:
        """Resolve API key for a named paper sub-account."""
        if self.mode == "live":
            return self.api_key()
        _key_vars: dict[str, list[str]] = {
            "zinc": ["ALPACA_API_KEY_PAPER_ZINC", "ALPACA_API_KEY_PAPER", "ALPACA_API_KEY"],
            "nyse": ["ALPACA_API_KEY_PAPER_NYSE"],
            "nasdaq": ["ALPACA_API_KEY_PAPER_NASDAQ"],
        }
        for var in _key_vars.get(account, []):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return self.api_key()

    def api_secret_for_account(self, account: str) -> str:
        """Resolve API secret for a named paper sub-account."""
        if self.mode == "live":
            return self.api_secret()
        _secret_vars: dict[str, list[str]] = {
            "zinc": ["ALPACA_API_SECRET_PAPER_ZINC", "ALPACA_API_SECRET_PAPER", "ALPACA_SECRET_KEY"],
            "nyse": ["ALPACA_API_SECRET_PAPER_NYSE"],
            "nasdaq": ["ALPACA_API_SECRET_PAPER_NASDAQ"],
        }
        for var in _secret_vars.get(account, []):
            val = os.environ.get(var, "").strip()
            if val:
                return val
        return self.api_secret()

    def credentials_configured(self) -> bool:
        """Return True when Alpaca API keys are present."""
        return bool(self.api_key() and self.api_secret())

    def paper_trading_enabled(self) -> bool:
        """True when running against Alpaca paper endpoints."""
        return self.mode == "paper"
