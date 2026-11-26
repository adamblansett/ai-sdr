import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_roles, resolve_request_settings
from app.core.telemetry import MetricsRegistry
from app.db.models import InboundReply, OutreachSequence, SequenceTouch
from app.db.session import get_db
from app.llm.router import LLMRouter, get_llm_router
from app.retrieval.embeddings import EmbeddingService, get_embedding_service
from app.sequences.composer import (
    generate_sequence,
    send_approved_touch,
    sequence_to_out,
    touch_to_out,
    update_touch_draft,
)
from app.sequences.delivery import EmailDeliveryService, get_email_delivery_service
from app.sequences.replies import ingest_inbound_reply, reply_to_out
from app.sequences.schemas import (
    InboundReplyIn,
    InboundReplyOut,
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
    embedding_service: EmbeddingService = Depends(get_embedding_service),
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
        embedding_service=embedding_service,
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
    request: Request,
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
    email_delivery: EmailDeliveryService = Depends(get_email_delivery_service),
) -> SequenceTouchOut:
    """Send an explicitly approved outbound touch (sales_manager/admin only)."""
    touch = await send_approved_touch(
        db,
        touch_id=touch_id,
        actor=actor,
        email_delivery=email_delivery,
    )
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, MetricsRegistry):
        metrics.inc("touches_sent_total")
    return touch_to_out(touch)


@router.get("/replies", response_model=list[InboundReplyOut])
async def list_inbound_replies(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[InboundReplyOut]:
    """List classified inbound prospect replies."""
    _ = actor
    replies = list(
        (
            await db.execute(
                select(InboundReply).order_by(InboundReply.received_at.desc()).limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [reply_to_out(r) for r in replies]


@router.post("/replies/inbound", response_model=InboundReplyOut)
async def ingest_inbound_reply_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> InboundReplyOut:
    """Classify an inbound prospect reply and execute opt-out/pause automation."""
    settings = resolve_request_settings(request)
    raw_body = await request.body()

    sig_header = request.headers.get("x-webhook-signature", "").strip()
    if sig_header:
        provided = sig_header.removeprefix("sha256=").strip().lower()
        expected = hmac.new(
            settings.effective_webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid inbound reply HMAC signature.",
            )
        actor = Actor(
            email="inbound-reply@email-webhook.local",
            role="admin",
            auth_method="webhook_hmac",
        )
    else:
        actor = await get_current_actor(request)
        if actor.role not in ("sdr", "sales_manager", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions; required role: sdr, sales_manager, admin.",
            )

    try:
        payload = InboundReplyIn.model_validate(json.loads(raw_body.decode("utf-8")))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inbound reply payload: {exc}",
        ) from exc

    reply = await ingest_inbound_reply(
        db,
        sender_email=payload.sender_email,
        subject=payload.subject,
        body=payload.body,
        sequence_id=payload.sequence_id,
        touch_id=payload.touch_id,
        actor=actor,
    )
    metrics = getattr(request.app.state, "metrics", None)
    if isinstance(metrics, MetricsRegistry):
        metrics.inc("replies_classified_total")
    return reply_to_out(reply)
