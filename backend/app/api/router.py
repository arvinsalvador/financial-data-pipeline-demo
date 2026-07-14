from fastapi import APIRouter

from app.api.routes.governance import router as governance_router
from app.api.routes.health import router as health_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(governance_router, tags=["governance"])
api_router.include_router(profiles_router, tags=["profiling"])
api_router.include_router(sources_router, tags=["sources"])
