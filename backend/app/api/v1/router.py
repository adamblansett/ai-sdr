from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.overview import router as overview_router
from app.audit.router import router as audit_router
from app.crm_sync.router import router as crm_router
from app.prospecting.router import router as prospecting_router
from app.qualification.router import router as qualification_router
from app.seed.router import router as seed_router
from app.sequences.router import router as sequences_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(overview_router)
api_v1_router.include_router(prospecting_router)
api_v1_router.include_router(qualification_router)
api_v1_router.include_router(sequences_router)
api_v1_router.include_router(crm_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(seed_router)
