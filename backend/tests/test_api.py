import pytest
from fastapi.testclient import TestClient

from app.api.routes import health as health_routes


def test_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "application": "CFO Financial Data Pipeline Demo",
        "environment": "development",
        "documentation": "/docs",
    }


def test_liveness_does_not_require_database(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readiness_when_database_is_available(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readiness_returns_503_when_database_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_routes, "database_is_ready", lambda _session: False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy"}


def test_general_health_reports_backend_and_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "application": "CFO Financial Data Pipeline Demo",
        "environment": "development",
        "backend": {"status": "healthy"},
        "database": {"status": "healthy"},
    }
