from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.demo_environment import (
    DemoEnvironmentError,
    cleanup_files,
    remove_files,
    require_development,
    safe_path,
)


def settings_for(root: Path, environment: str = "development") -> Settings:
    return Settings(
        DATABASE_URL="postgresql+psycopg://test:test@postgres/test",
        ENVIRONMENT=environment,
        UPLOAD_TEMP_DIRECTORY=root / "raw" / "uploads",
        REGISTERED_RAW_DIRECTORY=root / "raw" / "registered",
        REJECTED_RAW_DIRECTORY=root / "raw" / "rejected",
        MANIFESTS_DIRECTORY=root / "manifests",
        GENERATED_DATA_DIRECTORY=root / "generated",
        MESSY_GENERATED_ROOT=root / "generated" / "messy",
        MESSY_MANIFEST_ROOT=root / "generated" / "manifests" / "messy",
        MESSY_REPORT_ROOT=root / "generated" / "reports" / "messy",
        VALIDATION_REPORT_ROOT=root / "generated" / "reports" / "validation",
        RECONCILIATION_REPORT_ROOT=root / "reports" / "reconciliation" / "bank-ledger",
        PAYROLL_RECONCILIATION_REPORT_ROOT=root / "reports" / "reconciliation" / "payroll",
        INGESTION_REPORTS_DIRECTORY=root / "reports",
    )


def test_reset_refuses_production(tmp_path: Path) -> None:
    with pytest.raises(DemoEnvironmentError, match="disabled"):
        require_development(settings_for(tmp_path, "production"))


def test_cleanup_cannot_escape_data_root_or_touch_env(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with pytest.raises(DemoEnvironmentError, match="outside"):
        safe_path(tmp_path.parent / "source.py", settings)
    with pytest.raises(DemoEnvironmentError, match="Protected"):
        safe_path(tmp_path / ".env", settings)


def test_cleanup_preserves_gitkeep_and_selective_roots(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.REGISTERED_RAW_DIRECTORY.mkdir(parents=True)
    keep = settings.REGISTERED_RAW_DIRECTORY / ".gitkeep"
    data = settings.REGISTERED_RAW_DIRECTORY / "source.csv"
    keep.write_text("", encoding="utf-8")
    data.write_text("value\n1\n", encoding="utf-8")
    files = cleanup_files(settings, {"uploaded_files"})
    assert [item.path for item in files] == [data.resolve()]
    remove_files(files)
    assert keep.exists() and not data.exists()


def test_generated_clean_does_not_include_messy_files(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    clean = settings.GENERATED_DATA_DIRECTORY / "clean.csv"
    messy = settings.MESSY_GENERATED_ROOT / "messy.csv"
    clean.parent.mkdir(parents=True)
    messy.parent.mkdir(parents=True)
    clean.write_text("clean", encoding="utf-8")
    messy.write_text("messy", encoding="utf-8")
    files = cleanup_files(settings, {"generated_clean"})
    assert [item.path for item in files] == [clean.resolve()]
