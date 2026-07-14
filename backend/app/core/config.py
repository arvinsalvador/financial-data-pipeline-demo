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
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=250 * 1024 * 1024, gt=0)
    PROFILING_VERSION: str = "1.0.0"
    INGESTION_VERSION: str = "1.0.0"
    NORMALIZATION_VERSION: str = "1.0.0"
    GENERATOR_VERSION: str = "1.0.0"
    GENERATION_RANDOM_SEED: int = 20260714
    GENERATED_DATA_DIRECTORY: Path = Path("/data/generated")
    GENERATED_CUSTOMER_COUNT: int = Field(default=8, gt=0, le=1000)
    GENERATION_MIN_CUSTOMER_DEPOSIT: float = Field(default=0.01, ge=0)
    MESSY_GENERATOR_VERSION: str = "1.0.0"
    DEFAULT_DEFECT_SCENARIO: str = "standard_messy_v1"
    MESSY_GENERATION_RANDOM_SEED: int = 20260714
    MAX_DEFECTS_PER_RUN: int = Field(default=500, gt=0, le=10000)
    MAX_MUTATION_VALUE_LENGTH: int = Field(default=500, gt=0, le=10000)
    MESSY_GENERATED_ROOT: Path = Path("/data/generated/messy")
    MESSY_MANIFEST_ROOT: Path = Path("/data/generated/manifests/messy")
    MESSY_REPORT_ROOT: Path = Path("/data/generated/reports/messy")
    MESSY_DETERMINISM_VERIFICATION_ENABLED: bool = True
    SCENARIO_RULE_CONFLICT_POLICY: str = "skip_later"
    INGESTION_REPORTS_DIRECTORY: Path = Path("/data/reports")
    CSV_READ_CHUNK_SIZE: int = Field(default=1000, gt=0)
    MAX_SAMPLED_VALUES_PER_COLUMN: int = Field(default=5, gt=0, le=100)
    NULL_PERCENTAGE_WARNING_THRESHOLD: float = Field(default=50.0, ge=0, le=100)
    RUNNING_BALANCE_TOLERANCE: float = Field(default=0.01, ge=0)
    SUPPORTED_ENCODINGS: str = "utf-8-sig,utf-8"
    SUPPORTED_DATE_FORMATS: str = "%Y-%m-%d,%m/%d/%Y,%m/%-d/%Y,%m/%d/%Y %H:%M:%S,%Y-%m-%d %H:%M:%S"
    MAX_PROFILING_ROW_COUNT: int = Field(default=100000, gt=0)
    ENABLE_DEMO_ACTOR_HEADERS: bool = True
    DEFAULT_DEMO_TENANT_CODE: str = "demo_coffee_group"
    DEFAULT_DEMO_USER_EMAIL: str = "analyst@demo.local"

    @property
    def demo_actor_headers_enabled(self) -> bool:
        return self.ENABLE_DEMO_ACTOR_HEADERS and self.ENVIRONMENT in {"development", "test"}

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

    @property
    def supported_encodings(self) -> list[str]:
        return [value.strip() for value in self.SUPPORTED_ENCODINGS.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
