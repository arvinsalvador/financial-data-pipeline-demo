from typing import Literal

from pydantic import BaseModel


class RootResponse(BaseModel):
    application: str
    environment: str
    documentation: str


class ServiceStatus(BaseModel):
    status: Literal["healthy", "unhealthy"]


class HealthResponse(BaseModel):
    application: str
    environment: str
    backend: ServiceStatus
    database: ServiceStatus
