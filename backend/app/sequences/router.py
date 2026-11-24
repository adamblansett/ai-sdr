from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles
from app.db.models import OutreachSequence, SequenceTouch
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.sequences.composer import (
    generate_sequence,
    send_approved_touch,
    sequence_to_out,
    touch_to_out,
    update_touch_draft,
)
from app.sequences.schemas import (
    SequenceGenerateIn,
    SequenceOut,
    SequenceTouchOut,
    TouchUpdateIn,
)

router = APIRouter(prefix="/sequences", tags=["sequences"])


@router.get("", response_model=list[SequenceOut])
async def list_sequences(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[SequenceOut]:
    """List outbound sequences along with ordered touch drafts."""
    _ = actor
    sequences = list(
        (await db.execute(select(OutreachSequence).order_by(OutreachSequence.created_at.desc())))
        .scalars()
        .all()
    )
    all_touches = list((await db.execute(select(SequenceTouch))).scalars().all())
    by_seq: dict[str, list[SequenceTouch]] = {}
    for touch in all_touches:
        by_seq.setdefault(touch.sequence_id, []).append(touch)
    return [sequence_to_out(seq, by_seq.get(seq.id, [])) for seq in sequences]


@router.post("/generate", response_model=SequenceOut, status_code=status.HTTP_201_CREATED)
async def generate_sequence_endpoint(
    body: SequenceGenerateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    llm_router: LLMRouter = Depends(get_llm_router),
) -> SequenceOut:
    """Generate a personalized, signal-grounded sequence pending human approval."""
    sequence, touches = await generate_sequence(
        db,
        account_id=body.account_id,
        contact_id=body.contact_id,
        name=body.name,
        channel=body.channel,
        goal=body.goal,
        num_steps=body.num_steps,
        llm_router=llm_router,
        actor=actor,
    )
    return sequence_to_out(sequence, touches)


@router.patch("/touches/{touch_id}", response_model=SequenceTouchOut)
async def update_touch_endpoint(
    touch_id: str,
    body: TouchUpdateIn,
    actor: Actor = Depends(require_roles("sdr", "sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> SequenceTouchOut:
    """Edit an outbound touch draft (resets prior approval when modified)."""
    touch = await update_touch_draft(
        db,
        touch_id=touch_id,
        subject=body.subject,
        body=body.body,
        actor=actor,
    )
    return touch_to_out(touch)


@router.post("/touches/{touch_id}/send", response_model=SequenceTouchOut)
async def send_touch_endpoint(
    touch_id: str,
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> SequenceTouchOut:
    """Send an explicitly approved outbound touch (sales_manager/admin only)."""
    touch = await send_approved_touch(db, touch_id=touch_id, actor=actor)
    return touch_to_out(touch)
