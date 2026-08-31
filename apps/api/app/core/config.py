from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GEO Optimization Platform API"
    environment: str = "development"
    deployment_mode: str = "personal"
    database_url: str = "sqlite:///./geo_platform.db"
    cors_origins: str = "http://localhost:3000"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    kimi_api_key: str | None = None
    hunyuan_api_key: str | None = None
    ark_api_key: str | None = None
    qwen_api_key: str | None = None
    dashscope_api_key: str | None = None
    xiaoma_api_key: str | None = None
    article_sync_mcp_server_path: str | None = None
    article_sync_mcp_token: str | None = None
    anthropic_api_key: str | None = None
    claude_agent_models: str = "claude-sonnet-4-6,claude-opus-4-6,claude-haiku-4-5"
    hermes_api_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    openclaw_agent_id: str = "main"
    agent_max_concurrent_runs: int = 10
    agent_run_timeout_seconds: int = 900
    auth_secret: str = "dev-secret-change-me"
    internal_proxy_secret: str | None = None
    auto_create_tables: bool = False
    public_registration_enabled: bool = True
    registration_rate_limit_per_hour: int = 5
    login_rate_limit_per_15_minutes: int = 30
    observation_batch_rate_limit_per_hour: int = 10
    observation_active_batch_limit: int = 2
    observation_pending_task_limit: int = 10_000
    observation_daily_task_limit: int = 25_000
    collaboration_workspace_storage_quota_bytes: int = 2 * 1024 * 1024 * 1024
    collaboration_user_storage_quota_bytes: int = 512 * 1024 * 1024
    collaboration_attachment_count_quota: int = 2_000
    collaboration_upload_rate_limit_per_10_minutes: int = 30
    collaboration_message_rate_limit_per_10_minutes: int = 60
    collaboration_message_count_quota: int = 100_000
    collaboration_notification_rate_limit_per_hour: int = 30
    collaboration_notification_daily_workspace_limit: int = 500
    public_delivery_read_rate_limit_per_hour: int = 120
    public_delivery_confirm_rate_limit_per_hour: int = 10

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_driver(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    def validate_deployment(self) -> None:
        mode = self.deployment_mode.strip().lower()
        if mode not in {"personal", "lan", "cloud"}:
            raise RuntimeError("DEPLOYMENT_MODE must be personal, lan, or cloud")
        if self.auto_create_tables:
            raise RuntimeError(
                "AUTO_CREATE_TABLES=true is no longer supported. "
                "Back up the database and run Alembic migrations explicitly."
            )
        if mode == "lan" and self.database_url.startswith("sqlite"):
            raise RuntimeError("LAN deployment requires PostgreSQL; SQLite is personal mode only")
        if mode == "cloud" and self.database_url.startswith("sqlite"):
            raise RuntimeError("Cloud deployment requires PostgreSQL; SQLite is personal mode only")
        if mode == "lan" and self.auth_secret == "dev-secret-change-me":
            raise RuntimeError("LAN deployment requires a unique AUTH_SECRET")
        if mode == "cloud" and self.auth_secret == "dev-secret-change-me":
            raise RuntimeError("Cloud deployment requires a unique AUTH_SECRET")
        if mode == "lan" and (
            not self.internal_proxy_secret or len(self.internal_proxy_secret) < 32
        ):
            raise RuntimeError("LAN deployment requires an INTERNAL_PROXY_SECRET of at least 32 characters")
        if mode == "cloud" and (
            not self.internal_proxy_secret or len(self.internal_proxy_secret) < 32
        ):
            raise RuntimeError("Cloud deployment requires an INTERNAL_PROXY_SECRET of at least 32 characters")
        if mode == "lan" and self.public_registration_enabled:
            raise RuntimeError("LAN deployment requires PUBLIC_REGISTRATION_ENABLED=false")
        if mode == "cloud" and self.public_registration_enabled:
            raise RuntimeError("Cloud deployment requires PUBLIC_REGISTRATION_ENABLED=false")
        if self.is_production:
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("Production deployment requires PostgreSQL")
            if self.auth_secret == "dev-secret-change-me" or len(self.auth_secret) < 32:
                raise RuntimeError("Production deployment requires an AUTH_SECRET of at least 32 characters")
            if not self.internal_proxy_secret or len(self.internal_proxy_secret) < 32:
                raise RuntimeError(
                    "Production deployment requires an INTERNAL_PROXY_SECRET of at least 32 characters"
                )
            if not self.cors_origin_list or any(
                origin == "*" or not origin.startswith("https://")
                for origin in self.cors_origin_list
            ):
                raise RuntimeError("Production CORS_ORIGINS must contain only HTTPS origins")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise RuntimeError("Production ALLOWED_HOSTS must be explicit")
            if self.public_registration_enabled:
                raise RuntimeError("Production deployment requires PUBLIC_REGISTRATION_ENABLED=false")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
