import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://pipeline:pipeline@postgres:5432/pipeline"
)

from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
