from functools import lru_cache

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
    auto_create_tables: bool = True

    def validate_deployment(self) -> None:
        mode = self.deployment_mode.strip().lower()
        if mode not in {"personal", "lan"}:
            raise RuntimeError("DEPLOYMENT_MODE must be personal or lan")
        if mode == "lan" and self.database_url.startswith("sqlite"):
            raise RuntimeError("LAN deployment requires PostgreSQL; SQLite is personal mode only")
        if mode == "lan" and self.auth_secret == "dev-secret-change-me":
            raise RuntimeError("LAN deployment requires a unique AUTH_SECRET")
        if self.is_production:
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("Production deployment requires PostgreSQL")
            if self.auto_create_tables:
                raise RuntimeError("Production deployment requires AUTO_CREATE_TABLES=false")
            if self.auth_secret == "dev-secret-change-me" or len(self.auth_secret) < 32:
                raise RuntimeError("Production deployment requires an AUTH_SECRET of at least 32 characters")
            if not self.cors_origin_list or any(
                origin == "*" or not origin.startswith("https://")
                for origin in self.cors_origin_list
            ):
                raise RuntimeError("Production CORS_ORIGINS must contain only HTTPS origins")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise RuntimeError("Production ALLOWED_HOSTS must be explicit")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
