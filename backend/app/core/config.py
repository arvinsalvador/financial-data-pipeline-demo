from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "CFO Financial Data Pipeline Demo"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = Field(min_length=1)
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
