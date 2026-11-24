from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.core.auth import resolve_request_settings
from app.core.config import Settings, get_settings
from app.db.session import check_db_ready

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    app_name: str
    version: str
    environment: str
    llm_provider: str
    database: str = "ok"


@router.get("", response_model=HealthResponse)
@router.get("/live", response_model=HealthResponse)
async def health_live(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Return service liveness and runtime configuration summary."""
    cfg = resolve_request_settings(request, settings)
    return HealthResponse(
        status="ok",
        service=cfg.app_slug,
        app_name=cfg.app_name,
        version="0.1.0",
        environment=cfg.app_env,
        llm_provider=cfg.llm_default_provider,
        database="ok",
    )


@router.get("/ready", response_model=HealthResponse)
async def health_ready(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Verify database readiness before marking service ready."""
    cfg = resolve_request_settings(request, settings)
    db_engine = getattr(request.app.state, "db_engine", None)
    ready = db_engine is not None and await check_db_ready(db_engine)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            service=cfg.app_slug,
            app_name=cfg.app_name,
            version="0.1.0",
            environment=cfg.app_env,
            llm_provider=cfg.llm_default_provider,
            database="unreachable",
        )
    return HealthResponse(
        status="ok",
        service=cfg.app_slug,
        app_name=cfg.app_name,
        version="0.1.0",
        environment=cfg.app_env,
        llm_provider=cfg.llm_default_provider,
        database="ok",
    )
