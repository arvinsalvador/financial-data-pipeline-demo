from functools import lru_cache
from pathlib import Path

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
    UPLOAD_TEMP_DIRECTORY: Path = Path("/data/raw/uploads")
    REGISTERED_RAW_DIRECTORY: Path = Path("/data/raw/registered")
    REJECTED_RAW_DIRECTORY: Path = Path("/data/raw/rejected")
    MANIFESTS_DIRECTORY: Path = Path("/data/manifests")
    ALLOWED_SOURCE_FILE_EXTENSIONS: str = ".csv"
    ALLOWED_SOURCE_FILE_MIME_TYPES: str = (
        "text/csv,application/csv,application/vnd.ms-excel,text/plain,application/octet-stream"
    )
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=10 * 1024 * 1024, gt=0)

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def allowed_source_file_extensions(self) -> set[str]:
        return {
            extension.strip().lower()
            for extension in self.ALLOWED_SOURCE_FILE_EXTENSIONS.split(",")
            if extension.strip()
        }

    @property
    def allowed_source_file_mime_types(self) -> set[str]:
        return {
            mime_type.strip().lower()
            for mime_type in self.ALLOWED_SOURCE_FILE_MIME_TYPES.split(",")
            if mime_type.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
