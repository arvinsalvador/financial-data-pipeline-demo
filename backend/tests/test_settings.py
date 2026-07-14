import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_read_required_database_url() -> None:
    settings = Settings(DATABASE_URL="postgresql+psycopg://user:pass@db:5432/app")

    assert settings.database_url.endswith("@db:5432/app")
    assert settings.cors_origins == ["http://localhost:5173"]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
