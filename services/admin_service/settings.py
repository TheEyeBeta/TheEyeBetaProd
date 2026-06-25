"""Environment-backed configuration for admin-service."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default repo root: <repo>/services/admin_service/settings.py → 3 parents up.
_DEFAULT_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_DEFAULT_FRONTEND_ROOT = str(Path(__file__).resolve().parents[3] / "TheEyeBetaAdminFrontend")


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
    access_token_minutes: int = Field(default=45, validation_alias="JWT_ACCESS_MINUTES")
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
    admin_frontend_root: str = Field(
        default=_DEFAULT_FRONTEND_ROOT,
        validation_alias="ADMIN_FRONTEND_ROOT",
        description="TheEyeBetaAdminFrontend repo — templates, static, frontend_ia.",
    )

    grafana_overview_url: str = Field(
        default="http://grafana:3000/d/overview?orgId=1&kiosk=tv&theme=light",
        validation_alias="ADMIN_GRAFANA_OVERVIEW_URL",
        description="URL embedded in the dashboard iframe; kiosk mode hides Grafana chrome.",
    )
    terminal_watchlist: str = Field(
        default="AAPL,MSFT,NVDA,GOOGL,AMZN,TSLA,SPY,QQQ",
        validation_alias="ADMIN_TERMINAL_WATCHLIST",
        description="Comma-separated symbols for the terminal home quote monitor.",
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

    # Edge Route Registry / Cloudflare status (paths; never expose secrets in API responses).
    edge_cloudflared_repo_config: str = Field(
        default="",
        validation_alias="EDGE_CLOUDFLARED_REPO_CONFIG",
        description="Canonical cloudflared YAML in repo; auto-resolved when empty.",
    )
    edge_cloudflared_host_config: str = Field(
        default="/etc/cloudflared/config.yml",
        validation_alias="EDGE_CLOUDFLARED_HOST_CONFIG",
    )
    edge_dataapi_env_path: str = Field(
        default="",
        validation_alias="EDGE_DATAAPI_ENV_PATH",
        description="Data API .env for TRUSTED_HOSTS hostname list only; auto-resolved when empty.",
    )
    edge_dataapi_env_example_path: str = Field(
        default="",
        validation_alias="EDGE_DATAAPI_ENV_EXAMPLE_PATH",
    )
    cloudflare_api_token: str = Field(
        default="",
        validation_alias="CLOUDFLARE_API_TOKEN",
    )
    cloudflare_account_id: str = Field(
        default="",
        validation_alias="CLOUDFLARE_ACCOUNT_ID",
    )
    edge_mode: str = Field(
        default="auto",
        validation_alias="EDGE_MODE",
        description="auto | local | live — local forces dummy Cloudflare API mode.",
    )

    workers_mode: str = Field(
        default="auto",
        validation_alias="WORKERS_MODE",
        description="auto | local | live — local skips systemd host control.",
    )
    workers_heartbeat_stale_seconds: int = Field(
        default=900,
        validation_alias="WORKERS_HEARTBEAT_STALE_SECONDS",
        ge=60,
        le=86400,
    )
    services_mode: str = Field(
        default="auto",
        validation_alias="SERVICES_MODE",
        description="auto | local | live — local skips systemd host control.",
    )
    broker_mode: str = Field(default="paper", validation_alias="BROKER_MODE")
    broker_adapter_url: str = Field(
        default="http://127.0.0.1:7090",
        validation_alias="BROKER_ADAPTER_URL",
    )
    risk_service_url: str = Field(
        default="http://127.0.0.1:7060",
        validation_alias="RISK_SERVICE_URL",
    )
    risk_service_http_url: str = Field(
        default="http://127.0.0.1:8007",
        validation_alias="RISK_SERVICE_HTTP_URL",
        description="HTTP health/compute bridge (distinct from gRPC :7060).",
    )
    risk_default_portfolio_id: str = Field(
        default="",
        validation_alias="RISK_DEFAULT_PORTFOLIO_ID",
    )
    compliance_service_url: str = Field(
        default="http://127.0.0.1:7070",
        validation_alias="COMPLIANCE_SERVICE_URL",
    )
    compliance_service_http_url: str = Field(
        default="http://127.0.0.1:8008",
        validation_alias="COMPLIANCE_SERVICE_HTTP_URL",
        description="HTTP health/check bridge (distinct from gRPC :7070).",
    )
    compliance_default_portfolio_id: str = Field(
        default="",
        validation_alias="COMPLIANCE_DEFAULT_PORTFOLIO_ID",
    )
    compliance_recheck_instrument_id: int = Field(
        default=0,
        validation_alias="COMPLIANCE_RECHECK_INSTRUMENT_ID",
        ge=0,
    )
    oms_service_url: str = Field(
        default="http://127.0.0.1:7080",
        validation_alias="OMS_SERVICE_URL",
    )
    data_ingestion_url: str = Field(
        default="http://127.0.0.1:7010",
        validation_alias="DATA_INGESTION_URL",
    )
    snapshot_packager_url: str = Field(
        default="http://127.0.0.1:7011",
        validation_alias="SNAPSHOT_PACKAGER_URL",
    )
    admin_dataapi_url: str = Field(
        default="http://127.0.0.1:7000",
        validation_alias="ADMIN_DATAAPI_URL",
        description="Data API base URL for admin-service bridge (localhost on Mac server).",
    )
    dataapi_tunnel_url: str = Field(
        default="",
        validation_alias="DATAAPI_TUNNEL_URL",
        description="Public Data API hostname when bridge cannot reach 127.0.0.1:7000.",
    )
    admin_dataapi_client_id: str = Field(
        default="",
        validation_alias="ADMIN_DATAAPI_CLIENT_ID",
    )
    admin_dataapi_client_secret: str = Field(
        default="",
        validation_alias="ADMIN_DATAAPI_CLIENT_SECRET",
    )
    admin_dataapi_scopes: str = Field(
        default="market:read,admin:read",
        validation_alias="ADMIN_DATAAPI_SCOPES",
        description="Comma-separated scopes for service-token requests.",
    )
    admin_dataapi_verify_ssl: bool = Field(
        default=True,
        validation_alias="ADMIN_DATAAPI_VERIFY_SSL",
        description="Verify TLS when calling the Data API bridge (set false for some dev laptops).",
    )
    trading_mode: str = Field(
        default="auto",
        validation_alias="TRADING_MODE",
        description="auto | local | live probes",
    )
    trading_approval_token_minutes: int = Field(
        default=15,
        validation_alias="TRADING_APPROVAL_TOKEN_MINUTES",
        ge=1,
        le=120,
    )

    refresh_cookie_name: str = "admin_refresh_token"
    refresh_cookie_path: str = "/admin/auth"
    access_cookie_name: str = "admin_access_token"
    access_cookie_path: str = "/admin"

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

    def edge_cloudflared_repo_config_path(self) -> Path:
        """Canonical tunnel YAML committed in TheEyeBetaDataAPI."""
        if self.edge_cloudflared_repo_config.strip():
            return Path(self.edge_cloudflared_repo_config).expanduser().resolve()
        return (
            self.repo_root_path().parent
            / "TheEyeBetaDataAPI"
            / "TheEyeBetaDataAPI"
            / "deploy"
            / "cloudflared-config.yml"
        )

    def edge_dataapi_env_path_resolved(self) -> Path:
        """Runtime Data API .env (TRUSTED_HOSTS hostnames only when read)."""
        if self.edge_dataapi_env_path.strip():
            return Path(self.edge_dataapi_env_path).expanduser().resolve()
        return (
            self.repo_root_path().parent
            / "TheEyeBetaDataAPI"
            / "TheEyeBetaDataAPI"
            / ".env"
        )

    def edge_dataapi_env_example_path_resolved(self) -> Path:
        if self.edge_dataapi_env_example_path.strip():
            return Path(self.edge_dataapi_env_example_path).expanduser().resolve()
        return (
            self.repo_root_path().parent
            / "TheEyeBetaDataAPI"
            / "TheEyeBetaDataAPI"
            / ".env.example"
        )

    def cloudflare_credentials_present(self) -> bool:
        """True when live Cloudflare API could be used (token never exposed)."""
        return bool(self.cloudflare_api_token.strip())

    def edge_uses_local_mode(self) -> bool:
        """Dummy/local Cloudflare mode — no remote API calls."""
        mode = self.edge_mode.strip().lower()
        if mode == "local":
            return True
        if mode == "live":
            return False
        return not self.cloudflare_credentials_present()

    def workers_uses_local_mode(self) -> bool:
        """Skip systemd execution — audit and DB state only."""
        import sys

        mode = self.workers_mode.strip().lower()
        if mode == "local":
            return True
        if mode == "live":
            return False
        return not sys.platform.startswith("linux")

    def workers_systemd_enabled(self) -> bool:
        """True when systemd host control may be attempted."""
        import sys

        if self.workers_uses_local_mode():
            return False
        return sys.platform.startswith("linux")

    def services_uses_local_mode(self) -> bool:
        """Skip systemd execution — registry and audit only."""
        import sys

        mode = self.services_mode.strip().lower()
        if mode == "local":
            return True
        if mode == "live":
            return False
        return not sys.platform.startswith("linux")

    def services_systemd_enabled(self) -> bool:
        """True when allowlisted systemd control may be attempted."""
        import sys

        if self.services_uses_local_mode():
            return False
        return sys.platform.startswith("linux")

    def trading_uses_local_mode(self) -> bool:
        mode = self.trading_mode.strip().lower()
        if mode == "local":
            return True
        if mode == "live":
            return False
        return False

    def risk_http_base_url(self) -> str:
        """HTTP base URL for risk-service health and compute."""
        url = self.risk_service_http_url.strip()
        return url.rstrip("/") if url else "http://127.0.0.1:8007"

    def compliance_http_base_url(self) -> str:
        """HTTP base URL for compliance-service health and checks."""
        url = self.compliance_service_http_url.strip()
        return url.rstrip("/") if url else "http://127.0.0.1:8008"

    def oms_http_base_url(self) -> str:
        """HTTP base URL for OMS health and reconciliation."""
        url = self.oms_service_url.strip()
        return url.rstrip("/") if url else "http://127.0.0.1:7080"

    def data_ingestion_base_url(self) -> str:
        url = self.data_ingestion_url.strip()
        return url.rstrip("/") if url else "http://127.0.0.1:7010"

    def snapshot_packager_base_url(self) -> str:
        url = self.snapshot_packager_url.strip()
        return url.rstrip("/") if url else "http://127.0.0.1:7011"

    def dataapi_scopes_list(self) -> list[str]:
        """Parse ``ADMIN_DATAAPI_SCOPES`` into a deduplicated list."""
        raw = [part.strip() for part in self.admin_dataapi_scopes.split(",") if part.strip()]
        return list(dict.fromkeys(raw))

    def dataapi_credentials_present(self) -> bool:
        """True when service-client credentials are configured (secret never exposed)."""
        return bool(self.admin_dataapi_client_id.strip() and self.admin_dataapi_client_secret.strip())

    def dataapi_bridge_base_url(self) -> str:
        """Prefer local Data API URL; fall back to tunnel URL for off-box dev."""
        local = self.admin_dataapi_url.strip().rstrip("/")
        tunnel = self.dataapi_tunnel_url.strip().rstrip("/")
        if local:
            return local
        return tunnel

    def terminal_watchlist_symbols(self) -> list[str]:
        """Symbols shown on the terminal home quote monitor."""
        return [part.strip().upper() for part in self.terminal_watchlist.split(",") if part.strip()]

    def grafana_embed_enabled(self) -> bool:
        """Hide broken Docker-only Grafana iframes in local dev."""
        url = self.grafana_overview_url.lower()
        return "grafana:3000" not in url


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
