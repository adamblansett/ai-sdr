from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings, validate_production_security
from app.core.middleware import SecurityHeadersMiddleware


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings_override or get_settings()
    validate_production_security(cfg)

    application = FastAPI(
        title=cfg.app_name,
        version="0.1.0",
        description=(
            "Open-source, self-hosted AI Sales Development Representative platform for "
            "multi-channel outbound prospecting, lead qualification, personalized "
            "sequences, and CRM pipeline hygiene."
        ),
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(SecurityHeadersMiddleware, settings=cfg)
    application.include_router(api_v1_router, prefix=cfg.api_v1_prefix)
    return application


app = create_app()
