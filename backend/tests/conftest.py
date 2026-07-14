import os
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://pipeline:pipeline@postgres:5432/pipeline"
)

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import PipelineRun, PipelineRunStep, SourceFile


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        DATABASE_URL=os.environ["DATABASE_URL"],
        UPLOAD_TEMP_DIRECTORY=tmp_path / "raw" / "uploads",
        REGISTERED_RAW_DIRECTORY=tmp_path / "raw" / "registered",
        REJECTED_RAW_DIRECTORY=tmp_path / "raw" / "rejected",
        MANIFESTS_DIRECTORY=tmp_path / "manifests",
        MAX_UPLOAD_SIZE_BYTES=128,
    )


@pytest.fixture(autouse=True)
def isolate_registration_records(tmp_path: Path) -> Generator[None, None, None]:
    with SessionLocal() as session:
        baseline_run_id = session.scalar(select(func.max(PipelineRun.id))) or 0
        baseline_file_id = session.scalar(select(func.max(SourceFile.id))) or 0
    yield
    with SessionLocal() as session:
        new_run_ids = select(PipelineRun.id).where(PipelineRun.id > baseline_run_id)
        session.execute(
            delete(PipelineRunStep).where(PipelineRunStep.pipeline_run_id.in_(new_run_ids))
        )
        session.execute(delete(PipelineRun).where(PipelineRun.id > baseline_run_id))
        session.execute(delete(SourceFile).where(SourceFile.id > baseline_file_id))
        session.commit()
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def client(test_settings: Settings) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
