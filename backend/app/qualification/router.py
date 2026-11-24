from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import QualificationRecord
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.qualification.engine import evaluate_lead, qualification_to_out
from app.qualification.schemas import EvaluateLeadIn, QualificationOut

router = APIRouter(prefix="/qualification", tags=["qualification"])


@router.get("/records", response_model=list[QualificationOut])
async def list_qualification_records(
    account_id: str | None = Query(default=None),
    intent_tier: str | None = Query(default=None),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[QualificationOut]:
    """List qualification scorecards with BANT/MEDDIC and cited evidence."""
    _ = actor
    stmt = select(QualificationRecord).order_by(QualificationRecord.created_at.desc())
    if account_id:
        stmt = stmt.where(QualificationRecord.account_id == account_id)
    if intent_tier:
        stmt = stmt.where(QualificationRecord.intent_tier == intent_tier.strip().lower())
    records = list((await db.execute(stmt)).scalars().all())
    return [qualification_to_out(rec) for rec in records]


@router.post(
    "/evaluate",
    response_model=QualificationOut,
    status_code=status.HTTP_201_CREATED,
)
async def evaluate_lead_endpoint(
    body: EvaluateLeadIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> QualificationOut:
    """Run rubric ICP scoring and BANT/MEDDIC extraction for an account/contact."""
    record = await evaluate_lead(
        db,
        account_id=body.account_id,
        contact_id=body.contact_id,
        discovery_notes=body.discovery_notes,
        rubric_weights=body.rubric_weights,
        llm_router=llm_router,
        actor=actor,
    )
    return qualification_to_out(record)
