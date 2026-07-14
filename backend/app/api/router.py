from fastapi import APIRouter

from app.api.routes.generated_datasets import router as generated_datasets_router
from app.api.routes.governance import router as governance_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestions import router as ingestions_router
from app.api.routes.messy_datasets import router as messy_datasets_router
from app.api.routes.normalizations import router as normalizations_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(ingestions_router, tags=["ingestion"])
api_router.include_router(generated_datasets_router, tags=["generated datasets"])
api_router.include_router(messy_datasets_router, tags=["messy datasets"])
api_router.include_router(normalizations_router, tags=["normalization"])
api_router.include_router(governance_router, tags=["governance"])
api_router.include_router(profiles_router, tags=["profiling"])
api_router.include_router(sources_router, tags=["sources"])
