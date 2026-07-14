from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse, ServiceStatus

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


def database_is_ready(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        session.rollback()
        return False
    return True


@router.get("", response_model=HealthResponse)
def health(session: DatabaseSession, settings: ApplicationSettings) -> HealthResponse:
    database_status = "healthy" if database_is_ready(session) else "unhealthy"
    return HealthResponse(
        application=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        backend=ServiceStatus(status="healthy"),
        database=ServiceStatus(status=database_status),
    )


@router.get("/live", response_model=ServiceStatus)
def liveness() -> ServiceStatus:
    return ServiceStatus(status="healthy")


@router.get("/ready", response_model=ServiceStatus)
def readiness(response: Response, session: DatabaseSession) -> ServiceStatus:
    if not database_is_ready(session):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ServiceStatus(status="unhealthy")
    return ServiceStatus(status="healthy")
