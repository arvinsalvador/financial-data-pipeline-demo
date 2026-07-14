from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.schemas.health import RootResponse

settings = get_settings()

app = FastAPI(title=settings.APP_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", response_model=RootResponse)
def root() -> RootResponse:
    return RootResponse(
        application=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        documentation="/docs",
    )
