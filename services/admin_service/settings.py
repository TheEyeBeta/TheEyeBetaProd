"""Environment-backed configuration for admin-service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default repo root: <repo>/services/admin_service/settings.py → 3 parents up.
_DEFAULT_REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _normalize_pem(value: str) -> str:
    """Expand ``\\n`` escapes from sops/env into real PEM newlines."""
    return value.replace("\\n", "\n").strip()


class Settings(BaseSettings):
    """Admin-service configuration (env / sops-decrypted)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "admin-service"
    host: str = Field(default="0.0.0.0", validation_alias="ADMIN_SERVICE_HOST")
    port: int = Field(default=7200, validation_alias="ADMIN_SERVICE_PORT")

    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password_bcrypt: str = Field(default="", validation_alias="ADMIN_PASSWORD_BCRYPT")

    jwt_private_key: str = Field(default="", validation_alias="JWT_PRIVATE_KEY")
    jwt_public_key: str = Field(default="", validation_alias="JWT_PUBLIC_KEY")
    jwt_issuer: str = Field(default="theeyebeta-admin", validation_alias="JWT_ISSUER")
    access_token_minutes: int = Field(default=15, validation_alias="JWT_ACCESS_MINUTES")
    refresh_token_days: int = Field(default=7, validation_alias="JWT_REFRESH_DAYS")

    database_url: str = Field(
        default="postgresql://theeyebeta:changeme_postgres@127.0.0.1:5432/theeyebeta",
        validation_alias="ADMIN_DATABASE_URL",
    )
    nats_url: str = Field(default="nats://127.0.0.1:4222", validation_alias="NATS_URL")
    redis_url: str = Field(default="redis://127.0.0.1:6379/1", validation_alias="REDIS_URL")
    audit_service_url: str = Field(
        default="http://127.0.0.1:7110",
        validation_alias="AUDIT_SERVICE_URL",
    )
    agent_runtime_url: str = Field(
        default="http://127.0.0.1:8004",
        validation_alias="AGENT_RUNTIME_URL",
    )
    backtest_engine_url: str = Field(
        default="http://127.0.0.1:7100",
        validation_alias="BACKTEST_ENGINE_URL",
    )
    repo_root: str = Field(
        default=_DEFAULT_REPO_ROOT,
        validation_alias="ADMIN_REPO_ROOT",
        description="Filesystem root used to resolve agent constitution_path values.",
    )

    grafana_overview_url: str = Field(
        default="http://grafana:3000/d/overview?orgId=1&kiosk=tv&theme=light",
        validation_alias="ADMIN_GRAFANA_OVERVIEW_URL",
        description="URL embedded in the dashboard iframe; kiosk mode hides Grafana chrome.",
    )
    daily_backtest_strategy_id: str | None = Field(
        default=None,
        validation_alias="ADMIN_DAILY_BACKTEST_STRATEGY_ID",
        description="Strategy to run when the 'Run Daily Backtest' button is pressed.",
    )
    daily_backtest_days: int = Field(
        default=30,
        validation_alias="ADMIN_DAILY_BACKTEST_DAYS",
        ge=1,
        le=365,
    )
    daily_backtest_universe: str | None = Field(
        default=None,
        validation_alias="ADMIN_DAILY_BACKTEST_UNIVERSE",
    )
    audit_verify_hours: int = Field(
        default=24,
        validation_alias="ADMIN_AUDIT_VERIFY_HOURS",
        ge=1,
        le=720,
        description="Lookback window applied when the dashboard verify button runs.",
    )
    audit_page_limit: int = Field(
        default=50,
        validation_alias="ADMIN_AUDIT_PAGE_LIMIT",
        ge=1,
        le=500,
        description="Default page size for the audit log table.",
    )

    cors_cloudflare_origin: str = Field(
        default="https://admin.theeyebeta.store",
        validation_alias="ADMIN_CORS_CLOUDFLARE_ORIGIN",
    )
    cors_tailscale_origin: str = Field(
        default="http://127.0.0.1:7200",
        validation_alias="ADMIN_CORS_TAILSCALE_ORIGIN",
    )
    cookie_secure: bool = Field(default=False, validation_alias="ADMIN_COOKIE_SECURE")

    refresh_cookie_name: str = "admin_refresh_token"
    refresh_cookie_path: str = "/admin/auth"

    def jwt_private_pem(self) -> str:
        """Return PEM private key for RS256 signing."""
        return _normalize_pem(self.jwt_private_key)

    def jwt_public_pem(self) -> str:
        """Return PEM public key for RS256 verification."""
        return _normalize_pem(self.jwt_public_key)

    def cors_origins(self) -> list[str]:
        """Allowed browser origins (Cloudflare + Tailscale/local)."""
        return [self.cors_cloudflare_origin, self.cors_tailscale_origin]

    def repo_root_path(self) -> Path:
        """Return :attr:`repo_root` as a :class:`pathlib.Path`."""
        return Path(self.repo_root).resolve()


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
