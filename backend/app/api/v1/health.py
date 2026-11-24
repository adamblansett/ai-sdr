from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    app_name: str
    version: str
    environment: str
    llm_provider: str


@router.get("", response_model=HealthResponse)
@router.get("/live", response_model=HealthResponse)
@router.get("/ready", response_model=HealthResponse)
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return service health and runtime configuration summary."""
    return HealthResponse(
        status="ok",
        service=settings.app_slug,
        app_name=settings.app_name,
        version="0.1.0",
        environment=settings.app_env,
        llm_provider=settings.llm_default_provider,
    )
