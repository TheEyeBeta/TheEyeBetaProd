"""Service settings for snapshot-packager."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    service_name: str = "snapshot-packager"
    version: str = "0.1.0"
    host: str = Field(default="127.0.0.1", validation_alias="SNAPSHOT_PACKAGER_HOST")
    port: int = Field(default=7011, validation_alias="SNAPSHOT_PACKAGER_PORT")
