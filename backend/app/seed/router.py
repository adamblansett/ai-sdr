from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, require_roles, resolve_request_settings
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.seed.demo_data import seed_demo_dataset

router = APIRouter(prefix="/seed", tags=["seed"])


class SeedDemoOut(BaseModel):
    """Response summarizing demo dataset seeding."""

    seeded: bool
    message: str


@router.post("/demo", response_model=SeedDemoOut)
async def seed_demo_endpoint(
    request: Request,
    reset: bool = Query(default=False),
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> SeedDemoOut:
    """Seed (or reset and re-seed) the workspace with demo AI SDR records."""
    settings = resolve_request_settings(request)
    res: dict[str, Any] = await seed_demo_dataset(
        db,
        llm_router=llm_router,
        settings=settings,
        actor=actor,
        reset=reset,
    )
    return SeedDemoOut(**res)
