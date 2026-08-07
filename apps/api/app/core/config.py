from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GEO Optimization Platform API"
    environment: str = "development"
    database_url: str = "sqlite:///./geo_platform.db"
    cors_origins: str = "http://localhost:3000"
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    kimi_api_key: str | None = None
    hunyuan_api_key: str | None = None
    ark_api_key: str | None = None
    qwen_api_key: str | None = None
    dashscope_api_key: str | None = None
    xiaoma_api_key: str | None = None
    auth_secret: str = "dev-secret-change-me"
    auto_create_tables: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
